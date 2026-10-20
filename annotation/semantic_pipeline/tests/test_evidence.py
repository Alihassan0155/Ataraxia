"""Exact-source repair regressions, including read-only real failed drafts."""
import unittest
from pathlib import Path
from jsonschema import Draft202012Validator
from ataraxia.semantic.evidence import repair_quotes, EvidenceRepairError, passage_catalog, materialize_selection, materialize_field_passages
from ataraxia.semantic.storage import read
from ataraxia.semantic.representation import parse
from ataraxia.semantic.sources import annotations, metadata, bundle

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = read(ROOT/'semantic_pipeline/schemas/semantic_metadata.schema.json')


def draft(quote, field='speech_summary', value='Football training and running drills', source='transcript'):
    return {field:value, 'field_evidence':[{'field':field, 'source':source, 'quote':quote}]}


class EvidenceTests(unittest.TestCase):
    def test_summary_patch_preserves_other_fields(self):
        from ataraxia.semantic.evidence import replace_summary
        original = {'semantic_summary':'Old', 'emotion':'unchanged', 'field_evidence':[]}
        catalog = {'p000':{'source':'transcript', 'quote':'I discuss running.'}}
        repaired, passage = replace_summary(original, {'semantic_summary':'The speaker discusses running.', 'passage_id':'p000'}, catalog)
        self.assertEqual(passage, 'p000')
        self.assertEqual(repaired['emotion'], original['emotion'])
        self.assertEqual(original['semantic_summary'], 'Old')
        self.assertEqual(repaired['field_evidence'], [])

    def test_summary_patch_rejects_missing_evidence_or_extra_fields(self):
        from ataraxia.semantic.evidence import replace_summary
        for patch in ({'semantic_summary':None, 'passage_id':None},
                      {'semantic_summary':'Text', 'passage_id':'invented'},
                      {'semantic_summary':'Text', 'passage_id':'p000', 'intent':'changed'}):
            with self.assertRaises(ValueError):
                replace_summary({}, patch, {'p000':{'source':'transcript', 'quote':'Text'}})

    def test_every_field_needs_explicit_support_or_retraction(self):
        from test_contracts import extracted
        original = extracted()
        decisions = {name:None for name in SCHEMA['required'] if name not in (
            'field_evidence', 'unsupported_fields', 'extraction_confidence', 'category_ambiguity')}
        decisions['semantic_summary'] = 'p000'
        catalog = {'p000':{'source':'speech_text', 'quote':'A person describes a difficult training session.'}}
        repaired = materialize_field_passages(original, decisions, catalog, SCHEMA)
        self.assertEqual(repaired['semantic_summary'], original['semantic_summary'])
        self.assertEqual(repaired['extraction_confidence'], original['extraction_confidence'])
        self.assertEqual(repaired['primary_category'], 'unknown')
        with self.assertRaises(ValueError):
            materialize_field_passages(original, {}, catalog, SCHEMA)
        decisions['semantic_summary'] = None
        with self.assertRaises(ValueError):
            materialize_field_passages(original, decisions, catalog, SCHEMA)

    def test_lists_accept_multiple_real_ids_and_omitted_empty_fields(self):
        from test_contracts import extracted
        original = extracted()
        original['topics'] = ['Training']
        choices = {name:None for name in SCHEMA['required'] if name not in (
            'field_evidence', 'unsupported_fields', 'extraction_confidence', 'category_ambiguity')}
        choices['semantic_summary'] = 'p000'
        choices['topics'] = ['p000']
        del choices['secondary_categories']
        catalog = {'p000':{'source':'speech_text', 'quote':'A person describes a difficult training session.'}}
        fixed = materialize_field_passages(original, choices, catalog, SCHEMA)
        self.assertEqual(fixed['topics'], ['Training'])
        self.assertEqual(fixed['secondary_categories'], [])
        del choices['topics']
        with self.assertRaises(ValueError):
            materialize_field_passages(original, choices, catalog, SCHEMA)
    def test_selection_only_materializes_actual_source_passages(self):
        source = 'Football training and running drills.'
        catalog = passage_catalog({'visual':source})
        value = draft('bad quote')
        choice = {'evidence':[{'field':'speech_summary', 'passage_id':'p000'}], 'corrections':{}}
        fixed = materialize_selection(value, choice, catalog, SCHEMA)
        self.assertEqual(fixed['speech_summary'], value['speech_summary'])
        self.assertEqual(fixed['field_evidence'][0]['quote'], source)
        self.assertEqual(fixed['field_evidence'][0]['source'], 'visual')
        choice['evidence'][0]['passage_id'] = 'invented'
        with self.assertRaises(ValueError):
            materialize_selection(value, choice, catalog, SCHEMA)

    def test_selector_cannot_invent_descriptions_or_change_confidence(self):
        for corrections in ({'speech_summary':'A fabricated replacement'}, {'extraction_confidence':1}):
            with self.assertRaises(ValueError):
                materialize_selection(draft('bad'), {'evidence':[], 'corrections':corrections}, {}, SCHEMA)

    def test_catalog_never_truncates_indivisible_long_sentence(self):
        self.assertEqual(passage_catalog({'transcript':'word '*80}), {})

    def test_valid_short_unchanged(self):
        value = draft('Football training and running drills.')
        repaired, changes = repair_quotes(value, SCHEMA, {'transcript':value['field_evidence'][0]['quote']})
        self.assertEqual(repaired, value)
        self.assertEqual(changes, [])

    def test_long_verbatim_selects_full_relevant_sentence(self):
        text = 'Unrelated weather discussion. '*12+'Football training and running drills are demonstrated.'
        value = draft(text)
        repaired, changes = repair_quotes(value, SCHEMA, {'transcript':text})
        self.assertEqual(repaired['field_evidence'][0]['quote'], 'Football training and running drills are demonstrated.')
        self.assertLessEqual(len(repaired['field_evidence'][0]['quote']), 200)
        self.assertEqual(value['field_evidence'][0]['quote'], text)
        self.assertEqual(changes[0]['source'], 'transcript')

    def test_paraphrase_rejected(self):
        with self.assertRaises(EvidenceRepairError):
            repair_quotes(draft('He enjoys jogging.'), SCHEMA, {'transcript':'He likes running.'})

    def test_punctuation_and_spacing_restore_exact_source(self):
        source = 'He said “Don’t  stop.”\nKeep\ttraining.'
        original = 'He said "Don\'t stop." Keep training.'
        repaired, changes = repair_quotes(draft(original), SCHEMA, {'transcript':source})
        self.assertEqual(repaired['field_evidence'][0]['quote'], source)
        self.assertEqual(len(changes), 1)

    def test_short_quote_with_unusual_whitespace_is_unchanged(self):
        source = 'Run\tfast — but\n safely!'
        value = draft(source)
        repaired, changes = repair_quotes(value, SCHEMA, {'transcript':source})
        self.assertEqual(repaired, value)
        self.assertFalse(changes)

    def test_no_safe_excerpt_rejected(self):
        text = 'word '*80
        with self.assertRaises(EvidenceRepairError):
            repair_quotes(draft(text), SCHEMA, {'transcript':text})

    def test_multiple_invalid_entries_all_reported(self):
        value = draft('invented statement')
        value['field_evidence'].append({'field':'speech_summary', 'source':'taxonomy', 'quote':'Football'})
        with self.assertRaises(EvidenceRepairError) as caught:
            repair_quotes(value, SCHEMA, {'transcript':'Football training.'})
        self.assertEqual([i['index'] for i in caught.exception.issues], [0, 1])

    def test_visual_source_never_substituted_from_transcript(self):
        with self.assertRaises(EvidenceRepairError):
            repair_quotes(draft('A football match.', source='visual'), SCHEMA,
                          {'visual':'A person speaks.', 'transcript':'A football match.'})

    def test_ambiguous_canonical_passages_rejected(self):
        with self.assertRaises(EvidenceRepairError):
            repair_quotes(draft('Run fast'), SCHEMA, {'transcript':'Run  fast. Run\tfast.'})

    def test_negation_stays_in_whole_sentence(self):
        relevant = 'Football training is not safe without proper running drills.'
        text = 'Other unrelated information. '*15+relevant
        repaired, _ = repair_quotes(draft(text), SCHEMA, {'transcript':text})
        self.assertEqual(repaired['field_evidence'][0]['quote'], relevant)

    def test_saved_failures_remain_rejected_if_other_evidence_invalid(self):
        run = ROOT/'semantic_pipeline/runs/semantic_cuda_v3'
        if not (run/'frozen.json').exists():
            self.skipTest('Historical failure artifacts not present in this checkout')
        cfg = read(run/'frozen.json')['config']
        rows, _ = annotations(ROOT, cfg)
        meta = metadata(run)
        for vid in ('FV000002', 'FV000005'):
            paths = list((run/'videos'/vid).glob('*/attempts/*repair.txt'))
            self.assertTrue(paths, vid)
            job = bundle(ROOT, cfg, vid, rows[vid], meta[vid])
            value = parse(max(paths, key=lambda p:p.name).read_text(encoding='utf-8'))
            self.assertTrue(any(e.validator == 'maxLength' for e in Draft202012Validator(SCHEMA).iter_errors(value)))
            with self.assertRaises(EvidenceRepairError):
                repair_quotes(value, SCHEMA, job['sources'])


if __name__ == '__main__':
    unittest.main()
