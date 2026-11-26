"""Deterministic synthetic retrieval checks; real Stage 1 loader remains unchanged."""
from dataclasses import replace
from types import MappingProxyType
import unittest

import numpy as np

from research.recommendation.catalogue import Catalogue, build_catalogue
from research.recommendation.retrieval import CandidateRetriever, RetrievalConfig, RetrievalState
from research.recommendation.tests.test_catalogue import fixture


def unit(first=1., axis=1):
    vector = np.zeros(1024)
    vector[0] = first
    vector[axis] = np.sqrt(1 - first * first)
    return vector


def catalogue():
    base = build_catalogue(fixture()).records[0]
    vectors = [unit(.99 - i * .002) for i in range(20)]
    vectors += [unit(.86, 2), unit(.88, 3), unit(.2, 4), unit(-.5, 5)]
    records = tuple(replace(base, video_id=f'v{i:02}', category='Main' if i < 20 else 'Other',
                            recovery_suitability=.2 if i < 20 else [1., .8, 1., 1.][i - 20])
                    for i in range(len(vectors)))
    matrix = np.array(vectors, dtype=np.float32)
    ids = np.array([r.video_id for r in records])
    return Catalogue(records, matrix, np.empty((len(records), 12)), ids,
                     MappingProxyType({v: i for i, v in enumerate(ids)}), {})


class RetrievalTests(unittest.TestCase):
    def setUp(self):
        self.catalogue = catalogue()
        self.engine = CandidateRetriever(self.catalogue)
        self.state = RetrievalState(tuple(unit()))

    def test_top20_full_catalogue_ranking(self):
        result = self.engine.retrieve_relevant(self.state)
        expected = sorted(self.catalogue.records,
                          key=lambda r: (-self.catalogue.embeddings[self.catalogue.id_to_row[r.video_id], 0], r.video_id))[:20]
        self.assertEqual([c.video_id for c in result.candidates], [r.video_id for r in expected])
        self.assertEqual(result.catalogue_size, 24)
        self.assertEqual(len(result.candidates), 20)
        self.assertEqual([c.relevance_rank for c in result.candidates], list(range(1, 21)))
        self.assertEqual(result.candidates[0].affect.valence, self.catalogue.records[0].valence)
        self.assertTrue(all(c.eligibility.main_pool for c in result.candidates))

    def test_configurable_k(self):
        self.assertEqual(len(self.engine.retrieve_relevant(self.state, k=3).candidates), 3)
        engine = CandidateRetriever(self.catalogue, RetrievalConfig(main_k=7, alternative_k=1))
        self.assertEqual(len(engine.retrieve_relevant(self.state).candidates), 7)
        self.assertEqual(len(engine.retrieve_recovery_alternatives(self.state).candidates), 1)

    def test_both_alternatives_outside_top20_and_relevant(self):
        for method in (self.engine.retrieve_diverse_alternatives, self.engine.retrieve_recovery_alternatives):
            result = method(self.state)
            self.assertEqual(result.status, 'ok')
            self.assertEqual({c.video_id for c in result.candidates}, {'v20', 'v21'})
            for c in result.candidates:
                self.assertTrue(c.outside_main)
                self.assertGreater(c.relevance_rank, 20)
                self.assertGreaterEqual(c.relevance, result.relevance_floor)
            self.assertNotIn('v22', [c.video_id for c in result.candidates])
            self.assertNotIn('v23', [c.video_id for c in result.candidates])

    def test_diversity_uses_nearest_main_vector(self):
        result = self.engine.retrieve_diverse_alternatives(self.state)
        main = self.engine.retrieve_relevant(self.state)
        main_rows = [self.catalogue.id_to_row[c.video_id] for c in main.candidates]
        for c in result.candidates:
            row = self.catalogue.id_to_row[c.video_id]
            expected = 1 - max(self.catalogue.embeddings[row].astype(float) @ self.catalogue.embeddings[main_rows].astype(float).T)
            self.assertAlmostEqual(c.semantic_distance, expected)
            self.assertGreaterEqual(c.semantic_distance, .1)
            self.assertTrue(c.eligibility.diverse)

    def test_recovery_gain_and_order(self):
        result = self.engine.retrieve_recovery_alternatives(self.state)
        self.assertEqual([c.video_id for c in result.candidates], ['v20', 'v21'])
        self.assertAlmostEqual(result.recovery_baseline, .2)
        self.assertTrue(all(c.recovery_gain > result.config.recovery_margin and c.eligibility.recovery for c in result.candidates))

    def test_history_excluded_for_all_searches(self):
        state = replace(self.state, watched_ids=('v00', 'v20'))
        for method in (self.engine.retrieve_relevant, self.engine.retrieve_diverse_alternatives, self.engine.retrieve_recovery_alternatives):
            result = method(state)
            self.assertEqual(result.excluded_history_count, 2)
            self.assertTrue({'v00', 'v20'}.isdisjoint(c.video_id for c in result.candidates))
        self.assertEqual(self.engine.retrieve_relevant(state).candidates[-1].video_id, 'v21')

    def test_recent_and_none_history_rules(self):
        state = replace(self.state, watched_ids=('v00', 'v01', 'v01'))
        recent = CandidateRetriever(self.catalogue, RetrievalConfig(history_rule='recent', history_window=2))
        ids = [c.video_id for c in recent.retrieve_relevant(state).candidates]
        self.assertIn('v00', ids)
        self.assertNotIn('v01', ids)
        none = CandidateRetriever(self.catalogue, RetrievalConfig(history_rule='none'))
        self.assertEqual(none.retrieve_relevant(state).candidates, self.engine.retrieve_relevant(self.state).candidates)

    def test_preference_update_changes_ranking(self):
        changed = RetrievalState(tuple(np.eye(1, 1024, 2)[0]))
        before = self.engine.retrieve_relevant(self.state)
        after = self.engine.retrieve_relevant(changed)
        self.assertNotEqual(before.candidates, after.candidates)
        self.assertEqual(after.candidates[0].video_id, 'v20')
        self.assertEqual(self.engine.retrieve_relevant(self.state), before)

    def test_determinism_and_no_duplicates(self):
        for method in (self.engine.retrieve_relevant, self.engine.retrieve_diverse_alternatives, self.engine.retrieve_recovery_alternatives):
            a, b = method(self.state), method(self.state)
            self.assertEqual(a, b)
            self.assertEqual(len(a.candidates), len({c.video_id for c in a.candidates}))

    def test_ties_use_canonical_id(self):
        matrix = self.catalogue.embeddings.copy()
        matrix[1] = matrix[0]
        engine = CandidateRetriever(replace(self.catalogue, embeddings=matrix))
        self.assertEqual([c.video_id for c in engine.retrieve_relevant(self.state, 2).candidates], ['v00', 'v01'])

    def test_empty_alternatives_and_no_threshold_relaxation(self):
        engine = CandidateRetriever(self.catalogue, RetrievalConfig(min_relevance=1))
        for method in (engine.retrieve_diverse_alternatives, engine.retrieve_recovery_alternatives):
            result = method(self.state)
            self.assertEqual(result.candidates, ())
            self.assertEqual(result.reason, 'no_qualifying_alternative')
            self.assertEqual(result.qualifying_count, 0)
        engine = CandidateRetriever(self.catalogue, RetrievalConfig(min_semantic_distance=2, recovery_margin=1))
        self.assertEqual(engine.retrieve_diverse_alternatives(self.state).status, 'empty')
        self.assertEqual(engine.retrieve_recovery_alternatives(self.state).status, 'empty')

    def test_thresholds_configurable_and_inside_main_opt_in(self):
        engine = CandidateRetriever(self.catalogue, RetrievalConfig(outside_main_only=False, min_semantic_distance=0))
        self.assertTrue(any(not c.outside_main for c in engine.retrieve_diverse_alternatives(self.state, k=100).candidates))
        engine = CandidateRetriever(self.catalogue, RetrievalConfig(min_relevance=.9))
        self.assertEqual(engine.retrieve_recovery_alternatives(self.state).status, 'empty')

    def test_history_exhaustion_empty_and_short_catalogue(self):
        state = replace(self.state, watched_ids=tuple(self.catalogue.video_ids))
        for method in (self.engine.retrieve_relevant, self.engine.retrieve_diverse_alternatives, self.engine.retrieve_recovery_alternatives):
            self.assertEqual(method(state).reason, 'history_exhausted_catalogue')
        empty = CandidateRetriever(build_catalogue({}))
        self.assertEqual(empty.retrieve_relevant(self.state).reason, 'empty_catalogue')
        short = CandidateRetriever(build_catalogue(fixture()))
        self.assertEqual(len(short.retrieve_relevant(self.state).candidates), 2)
        self.assertEqual(short.retrieve_diverse_alternatives(self.state).candidates, ())

    def test_centroid_initialization_and_weights(self):
        state = self.engine.initialize_state(['Main', 'Other'])
        expected = sum(self.catalogue.embeddings[[i for i, r in enumerate(self.catalogue.records) if r.category == name]].astype(float).mean(0) /
                       np.linalg.norm(self.catalogue.embeddings[[i for i, r in enumerate(self.catalogue.records) if r.category == name]].astype(float).mean(0))
                       for name in ['Main', 'Other'])
        expected /= np.linalg.norm(expected)
        np.testing.assert_allclose(state.interest_vector, expected, atol=1e-14)
        self.assertEqual(state, self.engine.initialize_state({'Other': 1., 'Main': 1.}))
        self.assertNotEqual(state, self.engine.initialize_state({'Other': 3., 'Main': 1.}))

    def test_invalid_inputs_fail_explicitly(self):
        for weights in ([], ['missing'], ['Main', 'Main'], {'Main': 0}, {'Main': -1}, {'Main': float('nan')}, 'Main'):
            with self.subTest(weights=weights), self.assertRaises(ValueError):
                self.engine.initialize_state(weights)
        for vector in ([0.] * 1024, [float('nan')] * 1024, [[1.]], [float('inf')] * 1024):
            with self.assertRaises(ValueError):
                RetrievalState(vector)
        for kwargs in ({'main_k': 0}, {'min_relevance': float('nan')}, {'history_rule': 'bad'}, {'min_recovery': 2}):
            with self.assertRaises(ValueError):
                RetrievalConfig(**kwargs)
        for k in (0, -1, True, 2.5):
            with self.assertRaises(ValueError):
                self.engine.retrieve_relevant(self.state, k)
        with self.assertRaises(ValueError):
            self.engine.retrieve_relevant(RetrievalState((1.,)))
        with self.assertRaises(ValueError):
            self.engine.retrieve_relevant(replace(self.state, watched_ids=('unknown',)))

    def test_bad_catalogue_alignment_rejected(self):
        with self.assertRaises(ValueError):
            CandidateRetriever(replace(self.catalogue, video_ids=self.catalogue.video_ids[::-1]))
        matrix = self.catalogue.embeddings.copy()
        matrix[0] *= 2
        with self.assertRaises(ValueError):
            CandidateRetriever(replace(self.catalogue, embeddings=matrix))


if __name__ == '__main__':
    unittest.main()
