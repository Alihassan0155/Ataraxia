"""Verify Stage 4C orchestration and the existing eligibility boundaries."""
from dataclasses import replace
import unittest

import numpy as np

from research.recommendation.four_pools import FourPoolRetriever, POOL_ORDER
from research.recommendation.retrieval import CandidateRetriever, RetrievalConfig, RetrievalState
from research.recommendation.tests.test_retrieval import catalogue, unit


def ids(result):
    return [candidate.video_id for candidate in result.candidates]


def fixture(vectors, recovery):
    base = catalogue()
    records = tuple(replace(record, recovery_suitability=score)
                    for record, score in zip(base.records, recovery))
    video_ids = base.video_ids[:len(records)]
    return replace(base, records=records, embeddings=np.asarray(vectors, dtype=np.float64).reshape(-1, 1024),
                   affect=base.affect[:len(records)], video_ids=video_ids,
                   id_to_row={video_id: row for row, video_id in enumerate(video_ids)})


class FourPoolTests(unittest.TestCase):
    def test_direct_call_parity_and_exact_cosine_order_with_ties(self):
        source = fixture([unit(.8), unit(.9, 2), unit(.9, 3), unit(.87, 4)], [.2, .7, .8, .9])
        short = unit()
        long = unit(0, 3)
        history = ('v00',)
        runner = FourPoolRetriever(source, pool_size=2)
        result = runner.retrieve_pools(short, long, iter(history))
        direct = CandidateRetriever(source, RetrievalConfig(main_k=2, alternative_k=2))
        s, l = RetrievalState(short, history), RetrievalState(long, history)
        self.assertEqual(result.pools, (direct.retrieve_relevant(s), direct.retrieve_relevant(l),
                                       direct.retrieve_recovery_alternatives(s),
                                       direct.retrieve_diverse_alternatives(s)))
        for vector, pool in ((short, result.current), (long, result.stable)):
            expected = sorted(source.video_ids[1:],
                              key=lambda vid: (-(source.embeddings[source.id_to_row[vid]] @ vector), vid))
            self.assertEqual(ids(pool), expected[:2])
        self.assertEqual(result, runner.retrieve_pools(short, long, history))

    def test_top10_reference_differs_from_stage2_top20_for_both_alternatives(self):
        vectors = [unit(.89 - i * .002, 1) for i in range(10)]
        vectors += [unit(.81 - i * .003, 2) for i in range(10)]
        vectors += [unit(.75, 1)]
        source = fixture(vectors, [.2] * 10 + [.9] + [.2] * 9 + [.4])
        result = FourPoolRetriever(source).retrieve_pools(unit(), unit(), ())
        legacy = CandidateRetriever(source)
        state = RetrievalState(unit())
        self.assertEqual(ids(result.current), list(source.video_ids[:10]))
        self.assertEqual(len(legacy.retrieve_relevant(state).candidates), 20)
        self.assertIn('v10', ids(result.recovery))
        self.assertIn('v10', ids(result.diverse))
        self.assertNotIn('v10', ids(legacy.retrieve_recovery_alternatives(state, k=10)))
        self.assertNotIn('v10', ids(legacy.retrieve_diverse_alternatives(state, k=10)))
        self.assertAlmostEqual(result.recovery.recovery_baseline, .2)
        self.assertNotEqual(result.recovery.recovery_baseline,
                            legacy.retrieve_recovery_alternatives(state).recovery_baseline)

    def test_relevance_and_absolute_recovery_thresholds(self):
        below_relevance = np.nextafter(.30, 0.)
        below_recovery = np.nextafter(.60, 0.)
        source = fixture([unit(.4), unit(.30, 2), unit(below_relevance, 3), unit(.30, 4)],
                         [.2, .60, 1., below_recovery])
        result = FourPoolRetriever(source, 1).retrieve_pools(unit(), unit(), ())
        self.assertEqual(result.recovery.relevance_floor, .30)
        self.assertEqual(ids(result.recovery), ['v01'])
        self.assertEqual(result.diverse.qualifying_count, 2)

    def test_relative_relevance_distance_and_strict_gain_boundaries(self):
        cosine_below = np.nextafter(.90, 0.)
        gain_below = np.nextafter(.65, 0.)
        floor = 1. - .15
        source = fixture([unit(), unit(.90, 2), unit(cosine_below, 3),
                          unit(floor, 4), unit(np.nextafter(floor, 0.), 5)],
                         [.60, gain_below, .65, .65, 1.])
        result = FourPoolRetriever(source, 1).retrieve_pools(unit(), unit(), ())
        self.assertEqual(result.recovery.relevance_floor, floor)
        self.assertEqual(result.recovery.qualifying_count, 2)
        self.assertEqual(ids(result.recovery), ['v02'])
        self.assertEqual(result.diverse.qualifying_count, 2)
        self.assertEqual(ids(result.diverse), ['v03'])

    def test_overlap_history_partial_and_exhausted(self):
        source = fixture([unit(.9), unit(.88, 2), unit(.1, 3)], [.2, .9, .9])
        runner = FourPoolRetriever(source, 1)
        result = runner.retrieve_pools(unit(), unit(0, 2), ())
        self.assertEqual(POOL_ORDER, ('Current', 'Stable', 'Recovery', 'Diverse'))
        self.assertEqual(result.availability_mask, (True, True, True, True))
        self.assertEqual([ids(pool) for pool in result.pools], [['v00'], ['v01'], ['v01'], ['v01']])
        self.assertEqual(result.pairwise_overlap()[('Recovery', 'Diverse')], 1)
        partial = FourPoolRetriever(source).retrieve_pools(unit(), unit(), ('v00', 'v00', 'v01'))
        self.assertEqual([ids(pool) for pool in partial.pools], [['v02'], ['v02'], [], []])
        self.assertEqual(partial.availability_mask, (True, True, False, False))
        self.assertTrue(all(pool.excluded_history_count == 2 for pool in partial.pools))
        self.assertEqual(partial.recovery.reason, 'no_qualifying_alternative')
        exhausted = runner.retrieve_pools(unit(), unit(), source.video_ids)
        self.assertEqual(exhausted.availability_mask, (False,) * 4)
        self.assertTrue(all(pool.reason == 'history_exhausted_catalogue' for pool in exhausted.pools))
        empty = FourPoolRetriever(fixture([], []))
        self.assertTrue(all(pool.reason == 'empty_catalogue'
                            for pool in empty.retrieve_pools(unit(), unit(), ()).pools))

    def test_dynamic_feedback_and_invalid_inputs(self):
        source = catalogue()
        runner = FourPoolRetriever(source)
        initial = runner.retrieve_pools(unit(), unit(), ())
        changed = runner.retrieve_pools(unit(0, 4), unit(), ())
        self.assertNotEqual(ids(initial.current), ids(changed.current))
        self.assertEqual(initial.stable, changed.stable)
        served = ids(initial.current)[0]
        # A pass can change availability while both reference vectors stay fixed.
        passed = runner.retrieve_pools(unit(), unit(), (served,))
        self.assertTrue(all(served not in ids(pool) for pool in passed.pools))
        self.assertTrue(all(pool.excluded_history_count == 1 for pool in passed.pools))
        for k in (0, True, 2.5):
            with self.assertRaises(ValueError):
                FourPoolRetriever(source, k)
        for short, long, history in ((unit()[:5], unit(), ()), (unit(), unit() * np.nan, ()),
                                     (unit(), unit(), ('unknown',))):
            with self.assertRaises(ValueError):
                runner.retrieve_pools(short, long, history)
