"""CPU-only contracts; provided for the user, NOT executed during implementation."""
import copy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from types import SimpleNamespace

import numpy as np
from ataraxia.semantic import config, sources
from ataraxia.semantic.representation import parse, render, validate, normalize_missing, validation_feedback
from ataraxia.semantic.storage import atomic_bytes, digest, read, save_array, validate_array, write
from ataraxia.semantic.worker import Worker

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = read(ROOT/'semantic_pipeline/schemas/semantic_metadata.schema.json')
TAXONOMY = read(ROOT/'semantic_pipeline/configs/taxonomy.json')
TEMPLATE = read(ROOT/'semantic_pipeline/configs/embedding_template.json')


def extracted():
    result = {}
    lists = {'secondary_categories', 'topics', 'tags', 'subjects', 'activities', 'objects',
             'dialogue_themes', 'sound_effects', 'cultural_references', 'field_evidence', 'unsupported_fields'}
    for key in SCHEMA['required']:
        result[key] = [] if key in lists else None
    result.update(primary_category='unknown', video_format='unknown', content_style='unknown',
                  semantic_summary='A person describes a difficult training session.',
                  extraction_confidence=0.4, category_ambiguity=True)
    result['unsupported_fields'] = [k for k, v in result.items() if v is None or v == 'unknown']
    result['field_evidence'] = [{'field':'semantic_summary', 'source':'speech_text',
                                'quote':'describes a difficult training session'}]
    return result


def annotation():
    return {'video_id':'FV000001', 'valence':0.1, 'arousal':0.3, 'recovery_suitability':0.2,
            'emotions':dict(joy=1, sadness=0, anger=0, fear_anxiety=0, surprise=0,
                           disgust=0, calm_contentment=0, neutral=0),
            'dominant_emotion':'joy', 'confidence':0.5, 'model':'gemini-3.8-flash',
            'available_modalities':dict(visual=True, audio=True, speech_text=True, motion_temporal=True),
            'evidence':dict(visual='A person is talking.', audio=None,
                            speech_text='The person describes a difficult training session.', motion_temporal=None),
            'ambiguity_notes':''}


class Contracts(unittest.TestCase):
    def test_explicit_embedder_download_includes_bin_weights(self):
        from ataraxia.semantic.cli import main
        with patch('ataraxia.semantic.cli.root_path', return_value=ROOT), \
             patch('huggingface_hub.snapshot_download') as download:
            main(['download', '--models', 'embedder'])
        self.assertEqual(download.call_count, 1)
        self.assertEqual(download.call_args.args[0], 'BAAI/bge-m3')
        self.assertIn('*.bin', download.call_args.kwargs['allow_patterns'])
    def test_taxonomy_is_not_evidence_and_feedback_keeps_path(self):
        from jsonschema import Draft202012Validator
        value = extracted()
        value['field_evidence'][0]['source'] = 'taxonomy'
        error = next(Draft202012Validator(SCHEMA).iter_errors(value))
        feedback = validation_feedback(error)
        self.assertIn('field_evidence/0/source', feedback)
        self.assertIn('taxonomy', feedback)
        with self.assertRaises(Exception):
            validate(value, SCHEMA, TAXONOMY, {'taxonomy':'a category'})

    def test_only_nullable_blank_strings_become_null(self):
        original = extracted()
        original['music'] = '  '
        original['semantic_summary'] = ''
        value, changes = normalize_missing(original, SCHEMA)
        self.assertIsNone(value['music'])
        self.assertIn('music', value['unsupported_fields'])
        self.assertEqual(changes, ['music'])
        self.assertEqual(value['semantic_summary'], '')
        self.assertEqual(original['music'], '  ')

    def test_partial_append_and_conflicting_duplicates(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root/'annotations.jsonl'
            original = annotation()
            path.write_text(json.dumps(original)+'\n'+json.dumps(original)[:20], encoding='utf-8')
            rows, errors = sources.annotations(root, {'gemini_sources':['annotations.jsonl']})
            self.assertEqual(list(rows), ['FV000001'])
            self.assertEqual(errors, [])
            other = {**original, 'arousal':0.9}
            path.write_text(json.dumps(original)+'\n'+json.dumps(other)+'\n', encoding='utf-8')
            rows, errors = sources.annotations(root, {'gemini_sources':['annotations.jsonl']})
            self.assertEqual(rows, {})
            self.assertIn('Conflicting duplicate', errors[0]['error'])

    def test_quotes_and_unknowns_not_accuracy_guarantees(self):
        src = {'speech_text':'A person describes a difficult training session.'}
        value = extracted()
        self.assertEqual(validate(value, SCHEMA, TAXONOMY, src), value)
        value['field_evidence'][0]['quote'] = 'a fabricated quote'
        with self.assertRaises(ValueError):
            validate(value, SCHEMA, TAXONOMY, src)

    def test_taxonomy_and_duplicate_tags(self):
        value = extracted()
        value['primary_category'] = 'invented category'
        with self.assertRaises(ValueError):
            validate(value, SCHEMA, TAXONOMY, {})
        value = extracted()
        value['tags'] = ['Training', 'training']
        with self.assertRaises(ValueError):
            validate(value, SCHEMA, TAXONOMY, {})

    def test_render_determinism_and_no_affect_scores(self):
        job = {'sources':{k:'' for k in ('visual', 'audio', 'speech_text', 'motion_temporal',
                                        'transcript', 'caption', 'title', 'original_category')}}
        a = render(extracted(), job, TEMPLATE)
        self.assertEqual(a, render(extracted(), job, TEMPLATE))
        self.assertNotIn('valence', a[1])
        self.assertNotIn('recovery_suitability', a[1])

    def test_vectors_reject_dtype_nan_and_nonunit(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp)/'embedding.npy'
            good = np.zeros(1024, dtype=np.float32)
            good[0] = 1
            save_array(path, good)
            self.assertEqual(validate_array(path, 1024, 1e-4).shape, (1024,))
            for bad in (good.astype(np.float64), good*2, good*np.nan):
                save_array(path, bad)
                with self.assertRaises(ValueError):
                    validate_array(path, 1024, 1e-4)

    def test_resume_requires_same_frozen_definitions(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root/'source'
            source.write_text('original', encoding='utf-8')
            value = {'fingerprint':digest('original'), 'definition_hashes':{'prompt':config.sha(source)}}
            with patch.object(config, 'definitions', return_value=(value, {'prompt':source})):
                self.assertEqual(config.freeze(root, source, root/'run'), value)
                self.assertEqual(config.freeze(root, source, root/'run'), value)
            changed = copy.deepcopy(value)
            changed['fingerprint'] = digest('changed template')
            with patch.object(config, 'definitions', return_value=(changed, {'prompt':source})):
                with self.assertRaises(RuntimeError):
                    config.freeze(root, source, root/'run')

    def test_embedding_retry_reuses_saved_metadata(self):
        with TemporaryDirectory() as tmp:
            run = Path(tmp)
            worker = Worker(run, run/'config', run)
            # Production run/retry initialization supplies cfg before recovery.
            # This fixture exercises legacy metadata without the v2 policy.
            worker.cfg = {'extractor': {'evidence_policy': 'legacy-model-quotes'}}
            worker.frozen = {'fingerprint':digest('run')}
            worker.schema, worker.taxonomy, worker.template = SCHEMA, TAXONOMY, TEMPLATE
            src = {k:'' for k in ('visual', 'audio', 'speech_text', 'motion_temporal', 'transcript',
                                 'caption', 'title', 'original_category')}
            src['speech_text'] = 'A person describes a difficult training session.'
            job = {'video_id':'FV000001', 'source_fingerprint':digest(src), 'sources':src}
            directory = worker.directory(job)
            description, text = render(extracted(), job, TEMPLATE)
            atomic_bytes(directory/'embedding_input.txt', text.encode('utf-8'))
            artifact = {'video_id':job['video_id'], 'source_fingerprint':job['source_fingerprint'],
                        'run_fingerprint':worker.frozen['fingerprint'], 'semantic':extracted(),
                        'semantic_description':description, 'embedding_input_sha256':config.sha(directory/'embedding_input.txt')}
            write(directory/'semantic_metadata.json', artifact)
            self.assertEqual(worker.recover_metadata(job), artifact)
            atomic_bytes(directory/'embedding_input.txt', b'tampered')
            with self.assertRaises(ValueError):
                worker.recover_metadata(job)

    def test_oom_splits_only_batch_size(self):
        from ataraxia.semantic.models import split_oom
        class OOM(Exception):
            pass
        fake = SimpleNamespace(cuda=SimpleNamespace(OutOfMemoryError=OOM, empty_cache=lambda:None))
        calls = []
        def operation(items):
            calls.append(tuple(items))
            if len(items) > 1:
                raise OOM('synthetic')
            return [items[0]*2]
        with patch('ataraxia.semantic.models.gpu', return_value=fake):
            self.assertEqual(split_oom(operation, [1, 2, 3]), [2, 4, 6])
        self.assertIn((1, 2, 3), calls)


if __name__ == '__main__':
    unittest.main()
