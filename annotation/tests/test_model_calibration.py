import sys
import unittest
from pathlib import Path
import numpy as np

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from analyze_model_calibration import fit_scalar,apply_scalar,fit_emotion,apply_emotion,folds


class CalibrationTests(unittest.TestCase):
    def test_linear_mapping_fits_known_training_relation(self):
        x=np.array([0.,.2,.4,.6,.8]);y=.5*x+.1
        fit=fit_scalar(x,y,'linear')
        self.assertAlmostEqual(fit['slope'],.5)
        self.assertAlmostEqual(fit['intercept'],.1)
        np.testing.assert_allclose(apply_scalar(np.array([.1,.3]),fit,1),[.15,.25])

    def test_isotonic_pools_violations_and_duplicate_x_weights(self):
        fit=fit_scalar(np.array([0.,0.,1.,2.]),np.array([0.,2.,0.,2.]),'isotonic')
        np.testing.assert_allclose(fit['y_knots'],[2/3,2/3,2])
        self.assertTrue(all(a<=b for a,b in zip(fit['y_knots'],fit['y_knots'][1:])))
        self.assertEqual(fit['unique_input_levels'],3)

    def test_constant_model_scores_have_a_defined_linear_fallback(self):
        fit=fit_scalar(np.array([0.,0.,0.]),np.array([.2,.4,.6]),'linear')
        self.assertEqual(fit['slope'],0)
        self.assertAlmostEqual(fit['intercept'],.4)
        np.testing.assert_allclose(apply_scalar(np.array([0.,1.]),fit,1),[.4,.4])

    def test_emotion_offsets_are_train_only_and_normalized(self):
        x=np.tile([.8,.2,0,0,0,0,0,0],(3,1));y=np.tile([.4,.6,0,0,0,0,0,0],(3,1))
        fit=fit_emotion(x,y,'offset')
        np.testing.assert_allclose(apply_emotion(x,fit),y,atol=1e-12)
        prediction=apply_emotion(np.array([[0,1,0,0,0,0,0,0.]]),fit)
        self.assertAlmostEqual(float(prediction.sum()),1)
        self.assertTrue(np.all(prediction>=0))

    def test_shared_folds_cover_each_video_once_and_balance_strata(self):
        labels=['low']*19+['medium']*17+['high']*13
        split=folds(labels,5,20261007)
        self.assertEqual(sorted(int(v) for test in split for v in test),list(range(49)))
        self.assertLessEqual(max(map(len,split))-min(map(len,split)),1)
        for test in split:
            train=np.setdiff1d(np.arange(49),test)
            self.assertFalse(set(train)&set(test))
            self.assertEqual(len(train)+len(test),49)


if __name__=='__main__':unittest.main()
