"""Independent, single-writer semantic queue. Importing this module runs nothing."""
from datetime import datetime, timezone
import json
from pathlib import Path
import signal
import time

from ataraxia.runtime.config import resolve_path
from .config import freeze, check_freeze
from .sources import annotations, metadata, bundle
from .representation import parse, validate, render, normalize_missing, validation_feedback, response_errors
from .evidence import repair_quotes, passage_catalog, materialize_selection, materialize_field_passages, replace_summary
from .storage import (lock, read, write, atomic_bytes, sha, save_array,
                      complete_record, rebuild_manifest, validate_array)


def utc():
    return datetime.now(timezone.utc).isoformat()


class Worker:
    def __init__(self, root, config_path, run):
        self.root, self.config_path, self.run = root, config_path, run
        self.stopping = False
        self.extractor = self.embedder = None
        self.started = time.monotonic()
        self.completed_session = 0

    def event(self, kind, **values):
        entry = {'timestamp':utc(), 'event':kind, **values}
        path = self.run/'logs/events.jsonl'
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('a', encoding='utf-8') as f:
            f.write(json.dumps(entry, ensure_ascii=False)+'\n')
            f.flush()
        print(json.dumps(entry, ensure_ascii=False), flush=True)

    def state_path(self, job):
        return self.directory(job)/'state.json'

    def directory(self, job):
        return self.run/'videos'/job['video_id']/job['source_fingerprint']

    def state(self, job):
        path = self.state_path(job)
        return read(path) if path.exists() else {'attempts':0, 'next_retry_at':0}

    def failed(self, job, stage, exc):
        state = self.state(job)
        count = state['attempts']
        state.update(status='failed', stage=stage, error=f'{type(exc).__name__}: {exc}',
                     failed_at=utc(), next_retry_at=time.time()+min(
                         self.cfg['retry_max_seconds'], self.cfg['retry_base_seconds']*2**max(0, count-1)))
        write(self.state_path(job), state)
        self.event('failed', video_id=job['video_id'], stage=stage,
                   attempts=count, error=state['error'])

    def interrupted(self):
        return self.stopping or (self.run/'STOP').exists() or (self.run/'PAUSE').exists()

    def unload(self):
        from .models import release
        if self.extractor is not None:
            release(self.extractor)
            self.extractor = None
        if self.embedder is not None:
            release(self.embedder)
            self.embedder = None

    def recover_metadata(self, job):
        """Reuse a validated stage only if its exact input and provenance still match."""
        directory = self.directory(job)
        path = directory/'semantic_metadata.json'
        if not path.exists():
            return None
        value = read(path)
        if (value['video_id'] != job['video_id'] or
                value['source_fingerprint'] != job['source_fingerprint'] or
                value['run_fingerprint'] != self.frozen['fingerprint']):
            raise ValueError('Cached semantic metadata provenance mismatch')
        validate(value['semantic'], self.schema, self.taxonomy, job['sources'])
        if self.cfg['extractor'].get('category_policy')=='canonical-id-v1':
            from .category_ids import validate_selection
            validate_selection(value,self.taxonomy)
        if self.cfg['extractor'].get('evidence_policy') == 'deterministic-exact-v1':
            from .provenance import validate_provenance
            validate_provenance(value['semantic'], value.get('source_provenance'),
                                self.schema, self.taxonomy, job['sources'])
        description, text = render(value['semantic'], job, self.template)
        if value['semantic_description'] != description or value['embedding_input_sha256'] != sha(directory/'embedding_input.txt'):
            raise ValueError('Cached description/input integrity mismatch')
        if (directory/'embedding_input.txt').read_bytes() != text.encode('utf-8'):
            raise ValueError('Cached embedding text differs from frozen template')
        return value

    def extract(self, jobs, cached_outputs=None, cached_selections=None):
        if not jobs:
            return
        from .models import Extractor, release
        try:
            if self.cfg['memory_mode'] == 'staged' and self.embedder is not None:
                release(self.embedder)
                self.embedder = None
            if self.extractor is None and cached_outputs is None:
                self.event('loading_extractor')
                self.extractor = Extractor(self.cfg['extractor'], self.cache)
        except Exception as exc:
            for job in jobs:
                self.failed(job, 'extractor_load', exc)
            return
        if cached_outputs is not None:
            eligible = jobs
            outputs = [cached_outputs[j['video_id']] for j in jobs]
        else:
            texts, eligible = [], []
            for job in jobs:
                try:
                    texts.append(self.extractor.text(job, self.prompt, self.taxonomy, self.schema))
                    eligible.append(job)
                except Exception as exc:
                    self.failed(job, 'extraction_input', exc)
            if not eligible or self.interrupted():
                return
            try:
                outputs = self.extractor.generate(texts)
            except Exception as exc:
                for job in eligible:
                    self.failed(job, 'extraction', exc)
                return
        for job, output in zip(eligible, outputs):
            try:
                directory = self.directory(job)
                attempt = self.state(job)['attempts']
                atomic_bytes(directory/f'attempts/{attempt:04d}_{time.time_ns()}_extraction.txt', output.encode('utf-8'))
                repair_history = []
                source_provenance = None
                normalization_changes = []
                category_selection = None
                for repair_index in range(self.cfg['extractor'].get('repair_attempts', 0)+1):
                    try:
                        normalization_policy = self.cfg['extractor'].get('normalization_policy')
                        practical = normalization_policy in ('practical-v1', 'practical-v2-summary')
                        if practical:
                            from .normalization import parse_practical, normalize_semantic
                            draft=parse_practical(output)
                            if self.cfg['extractor'].get('category_policy')=='canonical-id-v1':
                                from .category_ids import decode_selection
                                draft,category_selection=decode_selection(draft,self.taxonomy)
                            value, normalization_changes = normalize_semantic(
                                draft, self.schema, self.taxonomy,
                                summary_fallback=normalization_policy == 'practical-v2-summary')
                            value, blanks = normalize_missing(value, self.schema)
                        else:
                            draft=parse(output)
                            if self.cfg['extractor'].get('category_policy')=='canonical-id-v1':
                                from .category_ids import decode_selection
                                draft,category_selection=decode_selection(draft,self.taxonomy)
                            value, blanks = normalize_missing(draft, self.schema)
                        if self.cfg['extractor'].get('evidence_policy') == 'deterministic-exact-v1':
                            from .provenance import build_provenance
                            value, source_provenance = build_provenance(value, self.schema, self.taxonomy, job['sources'], ignore_invalid=practical)
                            quote_repairs = []
                        else:
                            value, quote_repairs = repair_quotes(value, self.schema, job['sources'])
                        value = validate(value, self.schema, self.taxonomy, job['sources'])
                        if blanks:
                            self.event('blank_fields_normalized', video_id=job['video_id'], fields=blanks)
                        break
                    except Exception as exc:
                        if repair_index >= self.cfg['extractor'].get('repair_attempts', 0) or self.interrupted():
                            raise
                        reason = validation_feedback(exc)
                        try:
                            draft, _ = normalize_missing(parse(output), self.schema)
                            remaining = response_errors(draft, self.schema, self.taxonomy, job['sources'])
                        except Exception:
                            remaining = [reason]
                        self.event('repairing_json', video_id=job['video_id'], reason=reason)
                        repair_history.append({'repair':repair_index+1, 'reason':reason})
                        if self.extractor is None and not (cached_selections and job['video_id'] in cached_selections):
                            self.event('loading_extractor_for_cached_repair')
                            self.extractor = Extractor(self.cfg['extractor'], self.cache)
                        if self.cfg['extractor'].get('repair_format') in ('passage-selector-v1', 'field-passages-v2'):
                            try:
                                draft = parse(output)
                            except Exception:
                                # Malformed JSON cannot be safely merged: retain the bounded full repair.
                                draft = None
                            if draft is not None:
                                catalog = passage_catalog(job['sources'])
                                if cached_selections and job['video_id'] in cached_selections:
                                    selection_raw = cached_selections[job['video_id']]
                                else:
                                    repair_text = self.extractor.selector_text(draft, catalog, remaining, self.taxonomy, self.schema)
                                    selection_raw = self.extractor.generate([repair_text])[0]
                                atomic_bytes(directory/f'attempts/{attempt:04d}_{time.time_ns()}_selector.txt', selection_raw.encode('utf-8'))
                                materializer = materialize_field_passages if self.cfg['extractor']['repair_format'] == 'field-passages-v2' else materialize_selection
                                decisions = parse(selection_raw)
                                if (self.cfg['extractor'].get('summary_repair_attempts', 0) == 1
                                        and self.cfg['extractor']['repair_format'] == 'field-passages-v2'
                                        and decisions.get('semantic_summary') is None):
                                    # One bounded summary-only generation; never regenerate other fields.
                                    if self.extractor is None:
                                        self.event('loading_extractor_for_summary_repair')
                                        self.extractor = Extractor(self.cfg['extractor'], self.cache)
                                    self.event('repairing_summary', video_id=job['video_id'])
                                    summary_raw = self.extractor.generate([self.extractor.summary_text(catalog)])[0]
                                    atomic_bytes(directory/f'attempts/{attempt:04d}_{time.time_ns()}_summary.txt', summary_raw.encode('utf-8'))
                                    draft, passage_id = replace_summary(draft, parse(summary_raw), catalog)
                                    decisions['semantic_summary'] = passage_id
                                    repair_history[-1]['summary_repair'] = parse(summary_raw)
                                selected = materializer(draft, decisions, catalog, self.schema)
                                output = json.dumps(selected, ensure_ascii=False)
                                repair_history[-1].update(format=self.cfg['extractor']['repair_format'], selection=parse(selection_raw))
                            else:
                                repair_text = self.extractor.text(job, self.prompt, self.taxonomy, self.schema,
                                                                 repair={'invalid_draft':output, 'validation_error':reason})
                                output = self.extractor.generate([repair_text])[0]
                        else:
                            repair_text = self.extractor.text(job, self.prompt, self.taxonomy, self.schema,
                                                             repair={'invalid_draft':output, 'validation_error':reason,
                                                                     'remaining_errors':remaining})
                            output = self.extractor.generate([repair_text])[0]
                        atomic_bytes(directory/f'attempts/{attempt:04d}_{time.time_ns()}_repair.txt', output.encode('utf-8'))
                description, text = render(value, job, self.template)
                atomic_bytes(directory/'embedding_input.txt', text.encode('utf-8'))
                artifact = {'schema_version':self.cfg['schema_version'], 'video_id':job['video_id'],
                            'source_fingerprint':job['source_fingerprint'],
                            'run_fingerprint':self.frozen['fingerprint'], 'semantic':value,
                            'semantic_description':description,
                            'embedding_input_sha256':sha(directory/'embedding_input.txt'),
                            'extracted_at':utc(),
                            'extraction_repairs':repair_history, 'blank_fields_normalized':blanks,
                            'quote_repairs':quote_repairs}
                if source_provenance is not None:
                    artifact['source_provenance'] = source_provenance
                if category_selection is not None:
                    artifact['category_selection'] = category_selection
                if normalization_changes:
                    artifact['normalization_changes'] = normalization_changes
                write(directory/'semantic_metadata.json', artifact)
                state = self.state(job)
                state.update(status='metadata_ready', stage='embedding', next_retry_at=0)
                write(self.state_path(job), state)
            except Exception as exc:
                self.failed(job, 'semantic_validation', exc)

    def embed(self, jobs):
        from .models import Embedder, release
        eligible, texts = [], []
        for job in jobs:
            if self.state(job).get('status') == 'failed':
                continue
            try:
                value = self.recover_metadata(job)
                if value is not None:
                    eligible.append((job, value))
                    texts.append((self.directory(job)/'embedding_input.txt').read_text(encoding='utf-8'))
            except Exception as exc:
                self.failed(job, 'cached_metadata', exc)
        if not eligible or self.interrupted():
            return
        try:
            if self.cfg['memory_mode'] == 'staged' and self.extractor is not None:
                release(self.extractor)
                self.extractor = None
            if self.embedder is None:
                self.event('loading_embedder')
                self.embedder = Embedder(self.cfg['embedder'], self.cache)
        except Exception as exc:
            for job, _ in eligible:
                self.failed(job, 'embedder_load', exc)
            return
        # Reject oversized individual texts without blocking the rest of a batch.
        good, good_texts = [], []
        for pair, text in zip(eligible, texts):
            try:
                self.embedder.check_text(text)
                good.append(pair)
                good_texts.append(text)
            except Exception as exc:
                self.failed(pair[0], 'embedding_input', exc)
        width = self.cfg['embedder']['batch_size']
        for offset in range(0, len(good), width):
            if self.interrupted():
                break
            subset = good[offset:offset+width]
            try:
                vectors = self.embedder.encode(good_texts[offset:offset+width])
            except Exception as exc:
                for job, _ in subset:
                    self.failed(job, 'embedding', exc)
                continue
            for (job, artifact), vector in zip(subset, vectors):
                try:
                    check_freeze(self.root, self.config_path, self.run, self.frozen)
                    current = bundle(self.root, self.cfg, job['video_id'],
                                     {'annotation':job['annotation'],
                                      'annotation_sha256':job['hashes']['gemini'],
                                      'annotation_ref':job['references']['gemini']},
                                     self.metadata[job['video_id']])
                    if current['source_fingerprint'] != job['source_fingerprint']:
                        raise ValueError('Source evidence changed during processing; next poll creates a new version')
                    directory = self.directory(job)
                    save_array(directory/'embedding.npy', vector)
                    cfg = self.cfg['embedder']
                    validate_array(directory/'embedding.npy', cfg['expected_dimensions'], cfg['normalization_tolerance'])
                    rel = directory.relative_to(self.run).as_posix()
                    record = {**artifact, 'status':'complete', 'completed_at':utc(),
                              'source_references':job['references'], 'source_hashes':job['hashes'],
                              'gemini_prompt_provenance':job['gemini_prompt'],
                              'language_provenance':job['language_provenance'],
                              'transcript_budget':job['transcript_budget'],
                              'quality':{'missing_evidence':job['missing_evidence'],
                                         'available_modalities':job['available_modalities'],
                                         'evidence_coverage':(5-len(job['missing_evidence']))/5,
                                         'confidence_interpretation':'model-estimated, uncalibrated; not accuracy'},
                              'extractor':self.cfg['extractor'],
                              'extraction_prompt_version':self.cfg['extraction_prompt_version'],
                              'definitions':self.frozen['definition_hashes'],
                              'taxonomy_version':self.taxonomy['version'],
                              'template_version':self.template['version'],
                              'semantic_metadata_path':rel+'/semantic_metadata.json',
                              'semantic_metadata_sha256':sha(directory/'semantic_metadata.json'),
                              'embedding_input_path':rel+'/embedding_input.txt',
                              'embedding':{**cfg, 'dimensions':self.embedder.dimensions,
                                           'path':rel+'/embedding.npy', 'sha256':sha(directory/'embedding.npy')}}
                    write(directory/'record.json', record)
                    complete_record(self.run, directory/'record.json', self.frozen)
                    write(self.state_path(job), {'status':'complete', 'attempts':self.state(job)['attempts'],
                                               'completed_at':record['completed_at'], 'next_retry_at':0})
                    self.completed_session += 1
                    self.event('complete', video_id=job['video_id'])
                except RuntimeError:
                    raise  # Never retry a configuration change as an inference failure.
                except Exception as exc:
                    # Unverified record is not authoritative and cannot enter the manifest.
                    self.failed(job, 'output_validation', exc)

    def queue(self, rows):
        pending, completed, failures, invalid = [], [], [], []
        for vid, annotation in rows.items():
            try:
                if vid not in self.metadata:
                    raise ValueError('Gemini ID absent from frozen metadata manifest')
                job = bundle(self.root, self.cfg, vid, annotation, self.metadata[vid])
                job['annotation'] = annotation['annotation']  # RAM only; never copied into derived records.
                path = self.directory(job)/'record.json'
                if path.exists():
                    try:
                        complete_record(self.run, path, self.frozen)
                        completed.append(vid)
                        continue
                    except Exception as exc:
                        # Preserve damaged results; manual recovery uses a new run.
                        invalid.append({'video_id':vid, 'error':f'Invalid completion record: {exc}'})
                        continue
                state = self.state(job)
                if state['attempts'] >= self.cfg['max_attempts'] and state.get('status') == 'failed':
                    failures.append({'video_id':vid, **state})
                elif state.get('next_retry_at', 0) <= time.time():
                    pending.append(job)
                else:
                    failures.append({'video_id':vid, **state})
            except Exception as exc:
                invalid.append({'video_id':vid, 'error':str(exc)})
        return pending, completed, failures, invalid

    def run_loop(self, once=False):
        with lock(self.run/'worker.lock'):
            self.frozen = freeze(self.root, self.config_path, self.run)
            self.cfg = self.frozen['config']
            self.cache = resolve_path(self.root, self.cfg['cache_dir'])
            self.taxonomy = read(self.run/'definitions/taxonomy')
            self.template = read(self.run/'definitions/template')
            self.schema = read(self.run/'definitions/schema')
            self.prompt = (self.run/'definitions/prompt').read_text(encoding='utf-8-sig')
            self.metadata = metadata(self.run)
            prior_handlers = {}
            for sig in (signal.SIGINT, signal.SIGTERM):
                prior_handlers[sig] = signal.signal(sig, lambda *_: setattr(self, 'stopping', True))
            try:
                with lock(resolve_path(self.root, self.cfg['gpu_lock'])):
                    self.event('started', run_fingerprint=self.frozen['fingerprint'])
                    while not self.stopping and not (self.run/'STOP').exists():
                        check_freeze(self.root, self.config_path, self.run, self.frozen)
                        if (self.run/'RETRY_FAILED').exists():
                            for path in (self.run/'videos').glob('*/*/state.json'):
                                state = read(path)
                                if state.get('status') == 'failed':
                                    history = path.parent/'attempts'/f'retry_reset_{time.time_ns()}.json'
                                    write(history, state)
                                    state.update(attempts=0, next_retry_at=0, status='pending')
                                    write(path, state)
                            (self.run/'RETRY_FAILED').unlink()
                        rows, source_errors = annotations(self.root, self.cfg)
                        pending, completed, failures, invalid = self.queue(rows)
                        write(self.run/'reports/status.json', {
                            'updated_at':utc(), 'paused':(self.run/'PAUSE').exists(),
                            'complete':len(completed), 'pending':len(pending),
                            'failed_or_backoff':len(failures), 'invalid':invalid,
                            'failures':failures, 'source_errors':source_errors,
                            'awaiting_gemini':len(set(self.metadata)-set(rows)),
                            'completed_this_session':self.completed_session,
                            'videos_per_hour_this_session':self.completed_session*3600/max(1, time.monotonic()-self.started)})
                        rebuild_manifest(self.run, self.frozen)
                        if self.interrupted():
                            self.unload()
                        elif pending:
                            # Bounded two-stage queue, not per-video model loading.
                            batch = pending[:max(self.cfg['extractor']['batch_size'], self.cfg['embedder']['batch_size'])]
                            for job in batch:
                                state = self.state(job)
                                # An interrupted in-flight attempt continues without consuming another retry.
                                count = state['attempts'] if state.get('status') in ('processing', 'metadata_ready') else state['attempts']+1
                                state.update(attempts=count, status='processing', started_at=utc())
                                write(self.state_path(job), state)
                            missing = []
                            for job in batch:
                                try:
                                    if self.recover_metadata(job) is None:
                                        missing.append(job)
                                except Exception as exc:
                                    self.failed(job, 'cached_metadata', exc)
                            width = self.cfg['extractor']['batch_size']
                            for offset in range(0, len(missing), width):
                                if self.interrupted():
                                    break
                                self.extract(missing[offset:offset+width])
                            self.embed(batch)
                            continue
                        if once:
                            break
                        for _ in range(self.cfg['poll_seconds']):
                            if self.stopping or (self.run/'STOP').exists():
                                break
                            time.sleep(1)
            finally:
                self.unload()
                rebuild_manifest(self.run, self.frozen)
                self.event('stopped')
                for sig, handler in prior_handlers.items():
                    signal.signal(sig, handler)
