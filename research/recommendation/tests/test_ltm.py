"""Equation, lifecycle and standalone retrieval checks for Stage 4B."""
from dataclasses import replace
import math
import unittest

import numpy as np

from research.recommendation.ltm import LongTermMemory, LTMConfig
from research.recommendation.retrieval import CandidateRetriever
from research.recommendation.stm import ShortTermMemory
from research.recommendation.tests.test_retrieval import catalogue, unit


class LTMTests(unittest.TestCase):
    def setUp(self):
        self.onboarding = unit()
        self.item = unit(0, 1)
        base = catalogue()
        embeddings = base.embeddings.copy()
        embeddings[19] = self.onboarding
        embeddings[20:23] = [self.item, self.item, -self.onboarding]
        self.catalogue = replace(base, embeddings=embeddings)

    def memory(self, **kwargs):
        return LongTermMemory(self.catalogue, self.onboarding, LTMConfig(**kwargs))

    def test_exact_equation_on_successive_updates(self):
        memory = self.memory()
        expected = self.onboarding
        for video, ratio, liked, weight in [('v21', 0.9, False, 0.45),
                                            ('v22', 0.2, True, 1.0)]:
            embedding = self.catalogue.embeddings[self.catalogue.id_to_row[video]]
            expected = (1 - 0.02 * weight) * expected + 0.02 * weight * embedding.astype(float)
            expected /= np.linalg.norm(expected)
            self.assertEqual(memory.update(video, ratio, liked=liked), weight)
            np.testing.assert_allclose(memory.retrieval_state().interest_vector, expected,
                                       atol=1e-15, rtol=0)

    def test_gate_order_threshold_and_noop_exactness(self):
        memory = self.memory()
        initial = memory.retrieval_state()
        self.assertEqual(memory.update('v21', 0, liked=True), 0)
        self.assertEqual(memory.update('v21', 0.9, liked=True, immediate_pass=True), 0)
        self.assertEqual(memory.update('v21', math.nextafter(0.8, 0)), 0)
        self.assertEqual(memory.retrieval_state(), initial)
        self.assertEqual(memory.update('v21', 0.8), 0.4)
        self.assertEqual(memory.update('v21', 0.9, liked=True), 1.0)
        self.assertEqual(memory.update('v21', 0.1, liked=True), 1.0)
        for settings in ({'alpha_l': 0}, {'beta_l': 0}):
            frozen = self.memory(**settings)
            frozen.update('v21', 1)
            self.assertEqual(frozen.retrieval_state(), initial)

    def test_repeated_positive_feedback_adapts_slowly(self):
        memory = self.memory()
        affinity = [0.0]
        for _ in range(20):
            memory.update('v21', 1, liked=True)
            vector = memory.retrieval_state().interest_vector
            affinity.append(float(self.item @ vector))
            self.assertAlmostEqual(np.linalg.norm(vector), 1)
        self.assertTrue(all(a < b for a, b in zip(affinity, affinity[1:])))
        self.assertLess(affinity[1], 0.021)
        self.assertLess(affinity[-1], 0.4)

    def test_cross_session_retention_with_stm_reset(self):
        memory = self.memory()
        stm = ShortTermMemory(self.catalogue, self.onboarding)
        memory.update('v21', 0.2, liked=True)
        stm.update('v21', 0.2, liked=True)
        learned = memory.retrieval_state()
        self.assertEqual(stm.reset(self.onboarding).interest_vector, tuple(self.onboarding))
        self.assertEqual(memory.retrieval_state(stm.retrieval_state().watched_ids), learned)
        self.assertNotEqual(learned.interest_vector, tuple(self.onboarding))

    def test_new_user_reset_and_independent_instances(self):
        first, second = self.memory(), self.memory()
        first.update('v21', 0.2, liked=True)
        self.assertEqual(second.retrieval_state().interest_vector, tuple(self.onboarding))
        first.reset_for_user(self.item)
        self.assertEqual(first.retrieval_state().interest_vector, tuple(self.item))
        self.assertEqual(first.retrieval_state().watched_ids, ())

    def test_dynamic_top20_with_fixed_history(self):
        memory = self.memory(alpha_l=0.8)
        retriever = CandidateRetriever(self.catalogue)
        history = ('v21',)
        before = memory.retrieval_state(history)
        memory.update('v21', 0.1, liked=True)
        after = memory.retrieval_state(history)
        self.assertEqual(before.watched_ids, after.watched_ids)
        old = retriever.retrieve_relevant(before).candidates
        new = retriever.retrieve_relevant(after).candidates
        self.assertEqual(len(old), 20)
        self.assertEqual(len(new), 20)
        self.assertEqual(old[0].video_id, 'v19')
        self.assertEqual(new[0].video_id, 'v20')
        self.assertNotIn('v21', [item.video_id for item in new])

    def test_validation_and_degenerate_transition(self):
        for parameter in ('alpha_l', 'threshold', 'beta_l'):
            for value in (-1, 1.01, math.nan, math.inf, True):
                with self.assertRaises(ValueError):
                    LTMConfig(**{parameter: value})
        memory = self.memory(alpha_l=0.5)
        before = memory.retrieval_state()
        for ratio in (-1, 1.01, math.nan, math.inf, True):
            with self.assertRaises(ValueError):
                memory.update('v21', ratio)
        for flags in ({'liked': 1}, {'immediate_pass': 1}):
            with self.assertRaises(ValueError):
                memory.update('v21', 1, **flags)
        with self.assertRaises(ValueError):
            memory.update('unknown', 1)
        for onboarding in (np.zeros(1024), [1], np.full(1024, math.inf)):
            with self.assertRaises(ValueError):
                memory.reset_for_user(onboarding)
        self.assertEqual(memory.retrieval_state(), before)
        self.assertEqual(memory.update('v22', 1, liked=True), 1)
        self.assertEqual(memory.retrieval_state(), before)
        memory.reset_for_user(np.full(1024, 1e308))
        self.assertAlmostEqual(np.linalg.norm(memory.retrieval_state().interest_vector), 1)
