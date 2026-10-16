"""Manual CPU tests for v12 local summary fallback. No model inference."""
import json
from pathlib import Path
import unittest

from ataraxia.semantic.normalization import normalize_semantic, parse_practical
from ataraxia.semantic.provenance import build_provenance
from ataraxia.semantic.representation import validate
from test_deterministic_provenance import SCHEMA, TAXONOMY, draft

ROOT = Path(__file__).resolve().parents[2]


def process(value):
    result, changes = normalize_semantic(value, SCHEMA, TAXONOMY, summary_fallback=True)
    result, _ = build_provenance(result, SCHEMA, TAXONOMY, {}, ignore_invalid=True)
    validate(result, SCHEMA, TAXONOMY, {})
    return result, changes


class SummaryFallbackTests(unittest.TestCase):
    def test_missing_summary_prefers_existing_speech_summary(self):
        value = draft()
        del value['semantic_summary']
        value['speech_summary'] = 'A speaker discusses campus comedy and free speech.'
        value['meaning'] = 'A debate about public discussion on university campuses.'
        value['topics'] = ['Campus comedy', 'Free speech']
        result, changes = process(value)
        self.assertEqual(result['semantic_summary'], value['speech_summary'])
        self.assertEqual(result['meaning'], value['meaning'])
        self.assertEqual(result['topics'], value['topics'])
        self.assertIn('semantic_summary', result['unverified_fields'])
        self.assertTrue(any(c['reason']=='semantic_summary_from_speech_summary' for c in changes))
        self.assertNotIn('semantic_summary', value)

    def test_blank_or_placeholder_summary_falls_back_to_meaning(self):
        for missing in (None, '', '  ', 'unknown', 'null'):
            value = draft()
            value.update(semantic_summary=missing, speech_summary='Too short',
                         meaning='An existing description of a discussion about university policies.')
            result, changes = process(value)
            self.assertEqual(result['semantic_summary'], value['meaning'])
            self.assertTrue(any(c['reason']=='semantic_summary_from_meaning' for c in changes))

    def test_no_suitable_description_rejects_without_topic_stitching(self):
        for bad in (None, 'short', '1'*30, 'x'*1001):
            value = draft()
            value.update(semantic_summary=None, speech_summary=bad, meaning=None,
                         topics=['Useful topic'], tags=['Useful tag'])
            with self.assertRaisesRegex(ValueError, 'no suitable speech_summary or meaning'):
                process(value)

    def test_valid_summary_never_replaced(self):
        value = draft()
        value['speech_summary'] = 'Another existing description that should not replace a valid summary.'
        result, changes = process(value)
        self.assertEqual(result['semantic_summary'], value['semantic_summary'])
        self.assertFalse(any(c['field']=='semantic_summary' for c in changes))

    def test_existing_json_cleanup_and_optional_defaults_work_with_fallback(self):
        value = draft()
        for field in ('semantic_summary', 'setting', 'topics', 'objects'):
            del value[field]
        value['speech_summary'] = 'A speaker explains a training exercise and its practical purpose.'
        text = json.dumps(value)[:-1]+',}'
        result, _ = process(parse_practical(text))
        self.assertEqual(result['semantic_summary'], value['speech_summary'])
        self.assertIsNone(result['setting'])
        self.assertEqual(result['topics'], [])
        self.assertEqual(result['objects'], [])

    def test_v11_default_does_not_enable_new_fallback(self):
        value = draft()
        del value['semantic_summary']
        value['speech_summary'] = 'A speaker describes the purpose of a practical training exercise.'
        normalized, _ = normalize_semantic(value, SCHEMA, TAXONOMY)
        self.assertNotIn('semantic_summary', normalized)

    def test_saved_FV000014_v11_failure(self):
        paths = sorted((ROOT/'semantic_pipeline/runs/semantic_full_v11/videos/FV000014').glob('*/attempts/*_extraction.txt'))
        if not paths:
            self.skipTest('FV000014 v11 cached output unavailable')
        # Select a real cached missing-summary draft; never run the extractor.
        for path in paths:
            value = parse_practical(path.read_text(encoding='utf-8-sig'))
            if value.get('semantic_summary') is None:
                result, changes = process(value)
                self.assertIn(result['semantic_summary'], (value.get('speech_summary'), value.get('meaning')))
                self.assertTrue(any(c['field']=='semantic_summary' for c in changes))
                return
        self.skipTest('No missing-summary draft among available FV000014 outputs')


if __name__ == '__main__':
    unittest.main()
