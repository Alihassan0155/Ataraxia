"""Validate the STM equation and its integration with Stage 2 retrieval."""
from dataclasses import replace
import math
import unittest

import numpy as np

from research.recommendation.retrieval import CandidateRetriever
from research.recommendation.stm import ShortTermMemory, STMConfig
from research.recommendation.tests.test_retrieval import catalogue, unit


class STMTests(unittest.TestCase):
    def setUp(self):
        self.onboarding = unit()
        self.a, self.b = unit(0, 1), unit(0, 2)
        base = catalogue()
        embeddings = base.embeddings.copy()
        embeddings[-3:] = [self.a, self.b, -self.a]
        self.catalogue = replace(base, embeddings=embeddings)

    def memory(self, **kwargs):
        return ShortTermMemory(self.catalogue, self.onboarding, STMConfig(**kwargs))

    def assert_direction(self, state, total):
        np.testing.assert_allclose(state.interest_vector, total / np.linalg.norm(total),
                                   atol=1e-12)
        self.assertAlmostEqual(np.linalg.norm(state.interest_vector), 1.0)

    def test_recency_counts_every_interaction(self):
        memory = self.memory()
        memory.update('v21', 1.0)
        memory.update('v00', 0.0)
        state = memory.update('v22', 1.0)
        self.assert_direction(state, math.exp(-0.4) * self.a + self.b)

    def test_watch_ratio_when_decay_is_disabled(self):
        memory = self.memory(decay=0)
        memory.update('v21', 0.25)
        state = memory.update('v22', 0.75)
        self.assert_direction(state, 0.25 * self.a + 0.75 * self.b)

    def test_cold_start_and_session_reset(self):
        memory = self.memory()
        self.assert_direction(memory.retrieval_state(), self.onboarding)
        memory.update('v21', 1.0)
        state = memory.reset(self.b)
        self.assert_direction(state, self.b)
        self.assertEqual(state.watched_ids, ())

    def test_zero_watch_ages_out_positive_events_but_keeps_exclusion_history(self):
        memory = self.memory(history_window=2)
        self.assert_direction(memory.update('v00', 0.0), self.onboarding)
        memory.update('v21', 1.0)
        self.assert_direction(memory.update('v01', 0.0), self.a)
        state = memory.update('v02', 0.0)
        self.assert_direction(state, self.onboarding)
        self.assertEqual(state.watched_ids, ('v00', 'v21', 'v01', 'v02'))

    def test_stable_under_extreme_decay_and_tiny_watch_ratio(self):
        memory = self.memory(decay=1e308)
        memory.update('v22', 1.0)
        memory.update('v00', 0.0)
        memory.update('v21', math.ulp(0.0))
        for video_id in ('v01', 'v02'):
            state = memory.update(video_id, 0.0)
            self.assert_direction(state, self.a)

    def test_cancelled_direction_falls_back_to_onboarding(self):
        memory = self.memory(decay=0)
        memory.update('v21', 1.0)
        self.assert_direction(memory.update('v23', 1.0), self.onboarding)

    def test_invalid_inputs_do_not_advance_history(self):
        memory = self.memory()
        for ratio in (-1, 1.1, math.nan, math.inf, True):
            with self.assertRaises(ValueError):
                memory.update('v21', ratio)
        with self.assertRaises(ValueError):
            memory.update('unknown', 1.0)
        for vector in (self.a[:3], np.zeros(1024),
                       np.full(1024, math.inf), np.full(1024, math.nan)):
            with self.assertRaises(ValueError):
                memory.reset(vector)
        for params in ({'history_window': 0}, {'history_window': 2.5},
                       {'decay': -1}, {'decay': math.nan}, {'decay': math.inf}):
            with self.assertRaises(ValueError):
                STMConfig(**params)
        self.assertEqual(memory.retrieval_state().watched_ids, ())

    def test_top20_changes_due_to_preference_with_history_held_fixed(self):
        memory = self.memory()
        retriever = CandidateRetriever(self.catalogue)
        initial = memory.retrieval_state()
        updated = memory.update('v21', 1.0)
        fixed_preference = replace(initial, watched_ids=updated.watched_ids)
        before = retriever.retrieve_relevant(fixed_preference).candidates
        after = retriever.retrieve_relevant(updated).candidates
        self.assertEqual(len(before), 20)
        self.assertEqual(len(after), 20)
        self.assertNotEqual(before[0].video_id, after[0].video_id)
        self.assertNotIn('v21', [item.video_id for item in after])
        self.assertEqual(len({item.video_id for item in after}), 20)

    def test_equal_watch_ratios_like_bonus_is_unclipped(self):
        memory = self.memory(decay=0)
        memory.update('v21', 1.0)
        self.assert_direction(memory.update('v22', 1.0, liked=True), self.a + 1.5 * self.b)

    def test_partial_watch_like_normalizes_and_reset_clears_bonus(self):
        memory = self.memory()
        memory.update('v21', 0.75)
        state = memory.update('v22', 0.30, liked=True)
        self.assert_direction(state, math.exp(-0.2) * 0.75 * self.a + 0.80 * self.b)
        reset = memory.reset(self.onboarding)
        self.assertEqual(reset, self.memory().retrieval_state())
        self.assertEqual(memory.update('v00', 0), self.memory().update('v00', 0))

    def test_exact_watch_only_compatibility(self):
        original_api = self.memory()
        explicit_false = self.memory()
        zero_beta = self.memory(beta_like=0)
        for video, ratio, liked in [('v21', 0.25, True), ('v00', 0.0, False),
                                    ('v22', 1.0, True), ('v01', 0.8, False)]:
            expected = original_api.update(video, ratio)
            self.assertEqual(expected, explicit_false.update(video, ratio, liked=False))
            self.assertEqual(expected, zero_beta.update(video, ratio, liked=liked))

    def test_like_inputs_validated_before_history_changes(self):
        memory = self.memory()
        for beta in (-1, math.nan, math.inf, True):
            with self.assertRaises(ValueError):
                STMConfig(beta_like=beta)
        with self.assertRaises(ValueError):
            memory.update('v21', 1.2, liked=True)
        with self.assertRaises(ValueError):
            memory.update('v21', 0.2, liked=1)
        self.assertEqual(memory.retrieval_state().watched_ids, ())

    def test_like_reranks_top20_with_identical_served_history(self):
        self.catalogue.embeddings[19:21] = [self.a, self.b]
        baseline = self.memory(decay=0, beta_like=0)
        adjusted = self.memory(decay=0)
        for memory in (baseline, adjusted):
            memory.update('v21', 0.75)
            memory.update('v22', 0.5, liked=True)
        before, after = baseline.retrieval_state(), adjusted.retrieval_state()
        self.assertEqual(before.watched_ids, after.watched_ids)
        retriever = CandidateRetriever(self.catalogue)
        base_pool = retriever.retrieve_relevant(before).candidates
        like_pool = retriever.retrieve_relevant(after).candidates
        self.assertEqual(len(base_pool), 20)
        self.assertEqual(len(like_pool), 20)
        self.assertEqual(base_pool[0].video_id, 'v19')
        self.assertEqual(like_pool[0].video_id, 'v20')
