"""User-run CPU regressions; no scripts, models or downloads run on import."""
import copy
import json
from pathlib import Path
import unittest

from ataraxia.semantic.normalization import parse_practical, normalize_semantic
from ataraxia.semantic.provenance import build_provenance
from ataraxia.semantic.representation import validate
from test_deterministic_provenance import SCHEMA, TAXONOMY, draft

ROOT = Path(__file__).resolve().parents[2]


def process(value, sources=None):
    normalized, changes = normalize_semantic(value, SCHEMA, TAXONOMY)
    result, provenance = build_provenance(normalized, SCHEMA, TAXONOMY, sources or {}, ignore_invalid=True)
    validate(result, SCHEMA, TAXONOMY, sources or {})
    return result, changes, provenance


class PracticalNormalizationTests(unittest.TestCase):
    def test_original_failure_secondary_categories(self):
        for labels, expected in [(['Parody','Performance'], []),
                                 (['Entertainment & Animation','Performance'], ['Entertainment & Animation'])]:
            value = draft()
            value.update(primary_category='Comedy', subcategory='Sketches', secondary_categories=labels)
            result, changes, _ = process(value)
            self.assertEqual(result['secondary_categories'], expected)
            self.assertEqual(result['semantic_summary'], value['semantic_summary'])
            self.assertTrue(changes)

    def test_category_alias_spelling_and_unknown_fallback(self):
        for text, expected in [('humour','Comedy'), ('sports and fitnes','Sports & Fitness'),
                               ('Stand up','Comedy'), ('No matching category exists','unknown')]:
            value = draft()
            value['primary_category'] = text
            result, _, _ = process(value)
            self.assertEqual(result['primary_category'], expected)

    def test_invalid_model_evidence_cannot_block_metadata(self):
        for evidence in (None, 'unnecessary', [None, 123],
                         [{'field':'extraction_confidence','source':'taxonomy','quote':'0.9'}],
                         [{'bad':'shape'}]):
            value = draft()
            value['field_evidence'] = evidence
            result, _, provenance = process(value)
            self.assertEqual(result['semantic_summary'], value['semantic_summary'])
            self.assertEqual(result['field_evidence'], [])
            self.assertTrue(provenance['rejected_model_evidence'])

    def test_harmless_json_cleanup_does_not_edit_string_contents(self):
        text = '```json\n{"text":"literal ,} and ,]", "items":["a",],}\n```'
        self.assertEqual(parse_practical(text), {'text':'literal ,} and ,]', 'items':['a']})
        for bad in ('{"a":', '{"a":1,"a":2}', 'not JSON'):
            with self.assertRaises((ValueError,json.JSONDecodeError)):
                parse_practical(bad)

    def test_types_and_duplicates_without_erasing_descriptions(self):
        value = draft()
        value.update(topics=[' Fitness ','fitness',''], tags='Training',
                     extraction_confidence='0.75', category_ambiguity='false',
                     video_format='talking head', content_style='Comedic',
                     objects=None, meaning='A useful interpretation.', accidental_key='ignored')
        result, changes, _ = process(value)
        self.assertEqual(result['topics'], ['Fitness'])
        self.assertEqual(result['tags'], ['Training'])
        self.assertEqual(result['extraction_confidence'], 0.75)
        self.assertEqual(result['video_format'], 'talking_head')
        self.assertEqual(result['meaning'], value['meaning'])
        self.assertNotIn('accidental_key', result)
        self.assertEqual(value['accidental_key'], 'ignored')

    def test_core_semantic_errors_and_fabricated_retained_evidence_still_reject(self):
        for patch in ({'semantic_summary':''}, {'extraction_confidence':9}):
            value = draft()
            value.update(patch)
            with self.assertRaises(Exception):
                process(value)
        result, _, _ = process(draft())
        result['field_evidence'] = [{'field':'semantic_summary','source':'transcript','quote':'invented'}]
        with self.assertRaises(ValueError):
            validate(result, SCHEMA, TAXONOMY, {'transcript':'Something else.'})

    def test_real_cached_v10_FV000002_FV000005_FV000006(self):
        base = ROOT/'semantic_pipeline/runs/semantic_v10_canary6/videos'
        seen = []
        for vid in ('FV000002','FV000005','FV000006'):
            paths = sorted((base/vid).glob('*/attempts/*_extraction.txt'))
            if not paths:
                continue
            with self.subTest(video_id=vid):
                original = parse_practical(paths[0].read_text(encoding='utf-8-sig'))
                result, _, _ = process(original)
                for field in ('semantic_summary','topics','tags','speech_summary'):
                    self.assertEqual(result[field], original[field])
                seen.append(vid)
        if not seen:
            self.skipTest('Real v10 cache unavailable; synthetic regressions cover failures')


if __name__ == '__main__':
    unittest.main()
