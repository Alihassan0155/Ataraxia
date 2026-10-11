"""Check missing-field isolation and paired evaluation without real inference."""
import unittest
from unittest.mock import patch
import numpy as np
import evaluate as frozen
from evaluate_valid_fields import valid_field_metrics


class FieldEvaluationTests(unittest.TestCase):
    def data(self):
        x = np.tile([.4, .3, .2], (50, 1))
        p = np.full((50, 8), .125)
        y = x.copy()
        q = p.copy()
        q[0] = np.nan
        y[1, 0] = np.nan
        return (x, p, y, q, ['joy']*50,
                {'ali': [None]*50, 'zara': ['joy']*50}, [[]]+[['joy']]*49)

    def test_missing_fields_do_not_become_disagreements(self):
        values = self.data()
        result = valid_field_metrics(*values)
        for key in ('valence_mae', 'arousal_mae', 'recovery_suitability_mae',
                    'emotion_tv', 'emotion_jsd', 'scalar_plus_tv_composite'):
            self.assertAlmostEqual(result[key], 0.)
        self.assertIsNone(result['dominant_agreement_ali'])
        self.assertEqual(result['dominant_agreement_zara'], 1.)
        self.assertEqual(result['dominant_agreement_pooled'], 1.)
        self.assertTrue(np.isnan(values[3][0]).all())

    def test_paired_identical_models_remain_zero_with_missing_fields(self):
        values = {(m, v): self.data() for m in frozen.MODELS for v in ('raw', 'calibrated')}
        with patch.object(frozen, 'metric_values', valid_field_metrics):
            _, _, diffs = frozen.bootstrap(values, {'seed': 123, 'resamples': 20})
        for row in diffs:
            if row['difference_first_minus_second'] is not None:
                self.assertAlmostEqual(row['difference_first_minus_second'], 0.)
                self.assertAlmostEqual(row['ci_lower'], 0.)
                self.assertAlmostEqual(row['ci_upper'], 0.)


if __name__ == '__main__':
    unittest.main()
