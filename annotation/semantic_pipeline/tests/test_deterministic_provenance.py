"""User-run tests only. No inference, model loading, or downloads."""
import copy
import json
from pathlib import Path
import unittest

from ataraxia.semantic.provenance import build_provenance, unique_span
from ataraxia.semantic.representation import validate, parse

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = json.loads((ROOT/'semantic_pipeline/schemas/semantic_metadata.v2.schema.json').read_text())
TAXONOMY = json.loads((ROOT/'semantic_pipeline/configs/taxonomy.json').read_text())


def draft(summary='A speaker discusses a difficult training session.'):
    from test_contracts import extracted
    value = extracted()
    value.update(semantic_summary=summary, field_evidence=[], unverified_fields=[])
    return value


class DeterministicProvenanceTests(unittest.TestCase):
    def process(self, value, sources):
        result, provenance = build_provenance(value, SCHEMA, TAXONOMY, sources)
        validate(result, SCHEMA, TAXONOMY, sources)
        return result, provenance

    def test_exact_unique_reference_has_original_offsets(self):
        value = draft()
        sources = {'speech_text':'Introduction. '+value['semantic_summary']}
        result, provenance = self.process(value, sources)
        entry = result['field_evidence'][0]
        self.assertEqual(entry['quote'], value['semantic_summary'])
        ref = provenance['field_references']['semantic_summary'][0]
        self.assertEqual(sources[ref['source']][ref['start']:ref['end']], entry['quote'])
        self.assertIn('semantic_summary', result['unverified_fields'])

    def test_nonexact_or_repeated_text_never_normalized(self):
        self.assertIsNone(unique_span('Run fast', 'Run  fast'))
        self.assertIsNone(unique_span("It's safe", 'It’s safe'))
        self.assertIsNone(unique_span('safe', 'safe and safe'))
        self.assertEqual(unique_span('run\tfast', 'Please run\tfast!'), (7,15))

    def test_missing_quotes_preserves_description_and_marks_unverified(self):
        original = draft()
        original['meaning'] = 'The speaker reflects on training.'
        result, provenance = self.process(original, {'transcript':'Some different wording.'})
        self.assertEqual(result['semantic_summary'], original['semantic_summary'])
        self.assertEqual(result['meaning'], original['meaning'])
        self.assertEqual(result['field_evidence'], [])
        self.assertIn('meaning', result['unverified_fields'])
        self.assertNotIn('meaning', result['unsupported_fields'])
        self.assertEqual(provenance['field_status']['meaning'], 'unverified')
        self.assertEqual(original['unverified_fields'], [])

    def test_cached_provenance_cannot_claim_verified_or_change_offsets(self):
        from ataraxia.semantic.provenance import validate_provenance
        value = draft()
        sources = {'speech_text':value['semantic_summary']}
        result, provenance = self.process(value, sources)
        validate_provenance(result, provenance, SCHEMA, TAXONOMY, sources)
        altered = copy.deepcopy(provenance)
        altered['field_status']['semantic_summary'] = 'verified'
        with self.assertRaises(ValueError):
            validate_provenance(result, altered, SCHEMA, TAXONOMY, sources)
        altered = copy.deepcopy(provenance)
        altered['field_references']['semantic_summary'][0]['start'] = 900
        with self.assertRaises(ValueError):
            validate_provenance(result, altered, SCHEMA, TAXONOMY, sources)

    def test_taxonomy_is_separate_not_observed_evidence(self):
        value = draft()
        value['primary_category'] = 'Comedy'
        value['field_evidence'] = [{'field':'primary_category','source':'taxonomy','quote':'Comedy'}]
        result, provenance = self.process(value, {'visual':'Comedy'})
        self.assertFalse(any(e['field']=='primary_category' for e in result['field_evidence']))
        self.assertEqual(result['primary_category'], 'Comedy')
        self.assertEqual(provenance['rejected_model_evidence'][0]['reason'], 'non_observational_taxonomy')
        self.assertFalse(provenance['classification_provenance']['primary_category']['observationally_verified'])

    def test_model_citation_not_reassigned_to_other_source(self):
        value = draft()
        value['activities'] = ['Running']
        value['field_evidence'] = [{'field':'activities','source':'visual','quote':'Running'}]
        result, provenance = self.process(value, {'visual':'A person stands.', 'transcript':'Running'})
        self.assertFalse(any(e['field']=='activities' for e in result['field_evidence']))
        self.assertEqual(result['activities'], ['Running'])
        self.assertEqual(provenance['rejected_model_evidence'][0]['reason'], 'not_exact_or_not_unique')

    def test_overlong_model_quote_omitted_not_cropped(self):
        value = draft()
        value['field_evidence'] = [{'field':'semantic_summary','source':'transcript','quote':'x'*251}]
        result, provenance = self.process(value, {'transcript':'x'*251})
        self.assertEqual(result['field_evidence'], [])
        self.assertEqual(provenance['rejected_model_evidence'][0]['reason'], 'quote_length')

    def test_retained_fabricated_ambiguous_wrong_source_evidence_rejected(self):
        value = draft()
        result, _ = self.process(value, {})
        for source, quote, sources in [
            ('transcript','fabricated',{'transcript':'real text'}),
            ('speech_text',value['semantic_summary'],{'speech_text':value['semantic_summary']*2}),
            ('taxonomy','Comedy',{}),
        ]:
            bad = copy.deepcopy(result)
            bad['field_evidence'] = [{'field':'semantic_summary','source':source,'quote':quote}]
            with self.assertRaises(Exception):
                validate(bad, SCHEMA, TAXONOMY, sources)

    def test_malformed_evidence_and_invalid_taxonomy_still_fail(self):
        for evidence in (None, ['invalid'], [{'field':'topics','source':'transcript'}]):
            value = draft()
            value['field_evidence'] = evidence
            with self.assertRaises(ValueError):
                self.process(value, {})
        value = draft()
        value['primary_category'] = 'Made up label'
        with self.assertRaises(ValueError):
            self.process(value, {})
        with self.assertRaises(ValueError):
            parse('{"semantic_summary":')

    def test_absence_does_not_claim_contradiction_or_verification(self):
        value = draft('The subject discusses a training session.')
        value['topics'] = ['dangerous']
        result, provenance = self.process(value, {'transcript':'This is not dangerous.'})
        self.assertIn('topics', result['unverified_fields'])
        self.assertIn('not_performed', provenance['contradiction_check'])
        self.assertEqual(result['meaning'], None)
        self.assertIn('meaning', result['unsupported_fields'])

    def test_real_canary_FV000002_FV000005_FV000006(self):
        path = ROOT/'semantic_pipeline/reports/quality_audit_20261015_v1/canary_gemini_snapshot.jsonl'
        if not path.exists():
            self.skipTest('Real canary snapshot unavailable; synthetic regressions remain runnable')
        rows = {v['video_id']:v for v in (json.loads(line) for line in path.read_text(encoding='utf-8').splitlines())}
        for vid in ('FV000002','FV000005','FV000006'):
            with self.subTest(video_id=vid):
                sources = {k:(v or '') for k,v in rows[vid]['evidence'].items()}
                summary = sources['visual'] or sources['speech_text']
                value = draft(summary)
                value['field_evidence'] = [
                    {'field':'primary_category','source':'taxonomy','quote':'Comedy'},
                    {'field':'semantic_summary','source':'speech_text','quote':'Fabricated nonverbatim quotation'},
                ]
                result, provenance = self.process(value, sources)
                self.assertEqual(result['semantic_summary'], summary)
                self.assertEqual(len(provenance['rejected_model_evidence']), 2)
                for e in result['field_evidence']:
                    self.assertIsNotNone(unique_span(e['quote'], sources[e['source']]))

    def test_partial_list_references_do_not_verify_unmatched_members(self):
        value = draft()
        value['objects'] = ['keyboard', 'unseen vehicle']
        result, provenance = self.process(value, {'visual':'A keyboard lies here.'})
        self.assertEqual(result['objects'], value['objects'])
        self.assertIn('objects', result['unverified_fields'])
        self.assertEqual([e['quote'] for e in result['field_evidence']], ['keyboard'])
        self.assertEqual(provenance['field_status']['objects'], 'unverified')

    def test_legacy_schema_still_rejects_missing_evidence(self):
        from test_contracts import extracted, SCHEMA as old_schema
        value = extracted()
        value['field_evidence'] = []
        with self.assertRaises(ValueError):
            validate(value, old_schema, TAXONOMY, {})

    def test_cache_processing_does_not_load_extractor_for_bad_model_quotes(self):
        from tempfile import TemporaryDirectory
        from unittest.mock import patch
        from ataraxia.semantic.worker import Worker
        from ataraxia.semantic.storage import read
        with TemporaryDirectory() as tmp:
            worker = Worker(ROOT, ROOT/'semantic_pipeline/configs/pipeline_v10_canary6.json', Path(tmp))
            worker.cfg = {'memory_mode':'staged', 'schema_version':'semantic-record-v2',
                          'extraction_prompt_version':'semantic-extraction-v5',
                          'extractor':{'evidence_policy':'deterministic-exact-v1','repair_attempts':0}}
            worker.schema, worker.taxonomy, worker.template = SCHEMA, TAXONOMY, {}
            worker.frozen = {'fingerprint':'0'*64}
            worker.state = lambda job: {'attempts':1,'next_retry_at':0}
            worker.failed = lambda job, stage, exc: self.fail(f'{stage}: {exc}')
            job = {'video_id':'FV000002','source_fingerprint':'1'*64,'sources':{}}
            value = draft()
            value['field_evidence'] = [{'field':'primary_category','source':'taxonomy','quote':'Comedy'}]
            with patch('ataraxia.semantic.models.Extractor', side_effect=AssertionError('No GPU quote repair')), \
                 patch('ataraxia.semantic.worker.render', return_value=('Semantic description for test.', 'Embedding input for test.')):
                worker.extract([job], cached_outputs={'FV000002':json.dumps(value)})
            artifact = read(worker.directory(job)/'semantic_metadata.json')
            self.assertEqual(artifact['semantic']['semantic_summary'], value['semantic_summary'])
            self.assertEqual(artifact['extraction_repairs'], [])
            self.assertIn('semantic_summary', artifact['semantic']['unverified_fields'])

    def test_real_cached_canary_outputs_keep_all_content_values(self):
        run = ROOT/'semantic_pipeline/runs/semantic_v9_canary6'
        seen = 0
        for vid in ('FV000002','FV000005','FV000006'):
            paths = sorted((run/'videos'/vid).glob('*/attempts/*_extraction.txt'))
            if not paths:
                continue
            original = parse(paths[0].read_text(encoding='utf-8-sig'))
            # This regression checks transformation only; existing bad taxonomy or
            # malformed semantic fields must still fail full validation separately.
            result, provenance = build_provenance(original, SCHEMA, TAXONOMY, {})
            for field in SCHEMA['properties']:
                if field not in ('field_evidence','unsupported_fields','unverified_fields') and field in original:
                    self.assertEqual(result[field], original[field], (vid,field))
            self.assertEqual(result['field_evidence'], [])
            self.assertTrue(provenance['rejected_model_evidence'])
            seen += 1
        if not seen:
            self.skipTest('Cached real drafts unavailable')


if __name__ == '__main__':
    unittest.main()
