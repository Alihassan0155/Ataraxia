"""Local tests only: no GPU inference, API calls or human-label fabrication."""
import json
import unittest
import numpy as np
from support import ROOT, read, validate_freeze
from evaluate import calibration, confidence, metric_values, bootstrap


class WorkflowTests(unittest.TestCase):
    def test_exact_isolated_set_and_frozen_assets(self):
        cfg=validate_freeze()
        self.assertEqual(len(set(cfg['heldout_ids'])),50)
        self.assertFalse(set(cfg['heldout_ids'])&set(cfg['original_pilot_ids']))

    def test_frozen_calibration_applies_without_targets(self):
        plan={k:{'full_pilot_fit_parameters':{'method':'linear','slope':2.,'intercept':.1}} for k in ['valence','arousal','recovery_suitability']}
        plan['emotions']={'full_pilot_fit_parameters':{'method':'raw','offsets':[0.]*8,'fallback_distribution':[.125]*8}}
        x=np.array([[.8,.8,-.2]]);p=np.array([[.125]*8])
        sx,sp=calibration(x,p,plan)
        np.testing.assert_allclose(sx,[[1.,1.,0.]])
        np.testing.assert_allclose(sp.sum(axis=1),[1.])

    def test_degenerate_bootstrap_draws_counted(self):
        ci=confidence([None,float('nan'),0.,0.])
        self.assertEqual(ci['valid_bootstrap_draws'],2)
        self.assertEqual(ci['ci_lower'],0.)

    def test_templates_cover_the_frozen_set(self):
        import csv
        for h in ['ali','ghayas','zara']:
            with (ROOT/'human_annotations'/h/'annotations.csv').open(encoding='utf-8') as f:rows=list(csv.DictReader(f))
            self.assertEqual(len(rows),50)
            self.assertEqual({r['video_id'] for r in rows},set(read(ROOT/'config/frozen_config.json')['heldout_ids']))

    def test_paired_bootstrap_identical_models_have_zero_difference(self):
        v=np.linspace(.1,.8,50);x=np.column_stack((v,v,v));p=np.ones((50,8))/8
        data=(x,p,x+.01,p,['joy']*50,{h:['joy']*50 for h in ['ali','ghayas','zara']},[['joy']]*50)
        values={(model,variant):data for model in ['qwen','internvl','gemini'] for variant in ['raw','calibrated']}
        _,_,differences=bootstrap(values,{'seed':123,'resamples':20})
        for row in differences:
            if row['difference_first_minus_second'] is not None:
                self.assertAlmostEqual(row['difference_first_minus_second'],0.)
                self.assertAlmostEqual(row['ci_lower'],0.)
                self.assertAlmostEqual(row['ci_upper'],0.)


if __name__=='__main__':unittest.main()
