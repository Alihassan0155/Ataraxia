import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from build_human_soft_reference import reference_rows, distribution_match, evaluate, aggregate, quantile
from build_human_fieldwise_consensus import EMOTIONS


def human(vid='FV000001',**extra):
    r={'video_id':vid,'valence':5,'arousal':5,'recovery_suitability':5,
       **{e:0 for e in EMOTIONS},'joy':10,'dominant_emotion':'joy'}
    r.update(extra)
    return r


class SoftReferenceTests(unittest.TestCase):
    def build(self,a,b,expected=None):
        with tempfile.TemporaryDirectory() as t:
            pa,pb=Path(t)/'a.csv',Path(t)/'b.txt'
            with pa.open('w',newline='') as f:
                w=csv.DictWriter(f,fieldnames=list(a[0]));w.writeheader();w.writerows(a)
            pb.write_text(json.dumps(b))
            before=(pa.read_bytes(),pb.read_bytes())
            result=reference_rows(expected or ['FV000001'],{'a':pa,'b':pb})
            self.assertEqual(before,(pa.read_bytes(),pb.read_bytes()))
            return result

    def test_extreme_disagreement_is_retained(self):
        rows,_,_=self.build([human(valence=0,arousal=0,recovery_suitability=0)],
                           [human(valence=10,arousal=10,recovery_suitability=10,joy=0,neutral=10,dominant_emotion='neutral')])
        r=rows[0]
        self.assertEqual(r['valence_human_mean'],5)
        self.assertEqual(r['valence_human_mean_model_scale'],0)
        self.assertEqual(r['valence_uncertainty'],10)
        self.assertEqual(r['arousal_human_mean_model_scale'],.5)
        self.assertEqual(r['emotion_tv'],1)
        self.assertEqual(r['emotion_jsd'],1)
        self.assertEqual(r['overall_human_uncertainty'],1)
        self.assertEqual(r['pooled_emotion_distribution']['joy'],.5)
        self.assertEqual(r['pooled_distribution_dominant_set'],['joy','neutral'])
        self.assertTrue(r['dominant_disagreement'])
        self.assertEqual(r['human_a_dominant'],'joy')
        self.assertEqual(r['human_b_dominant'],'neutral')

    def test_exact_mixture_is_rewarded_without_hard_consensus(self):
        a={e:0 for e in EMOTIONS};b=a.copy()
        a.update(joy=.6,calm_contentment=.3,neutral=.1)
        b.update(joy=.2,calm_contentment=.6,neutral=.2)
        pooled={e:(a[e]+b[e])/2 for e in EMOTIONS}
        metrics=distribution_match(pooled,a,b,pooled)
        self.assertEqual(metrics['emotion_tv_to_pool'],0)
        self.assertEqual(metrics['emotion_jsd_to_pool'],0)
        self.assertTrue(metrics['mixture_closer_than_both_humans_tv'])
        self.assertTrue(metrics['mixture_closer_than_both_humans_jsd'])

    def test_invalid_scalar_and_missing_row_do_not_poison_others(self):
        rows,_,_=self.build([human(valence='nan')],[human()],['FV000001','FV000131'])
        r,missing=rows
        self.assertIsNone(r['valence_human_mean'])
        self.assertEqual(r['arousal_human_mean'],5)
        self.assertIsNotNone(r['pooled_emotion_distribution'])
        self.assertIsNone(r['overall_human_uncertainty'])
        self.assertIsNone(missing['uncertainty_bin'])
        self.assertIsNone(missing['pooled_emotion_distribution'])

    def test_tied_quantiles_are_not_split_by_video_id(self):
        a=[human(f'FV{i:06d}') for i in range(1,5)]
        rows,_,bounds=self.build(a,a,[r['video_id'] for r in a])
        self.assertEqual(bounds,[0,0])
        self.assertTrue(all(r['uncertainty_bin']=='low' for r in rows))
        self.assertEqual(quantile([0,3,6,9],1/3),3)

    def test_metric_specific_coverage_survives_one_missing_field(self):
        rows,_,_=self.build([human(valence='nan')],[human()])
        record={'valence':0,'arousal':.5,'recovery_suitability':.5,
                'emotions':{e:float(e=='joy') for e in EMOTIONS},'dominant_emotion':'joy'}
        result=aggregate('test','overall',[evaluate('test',record,rows[0])])
        self.assertEqual(result['valence_n'],0)
        self.assertEqual(result['arousal_n'],1)
        self.assertEqual(result['arousal_mae'],0)
        self.assertEqual(result['emotion_tv_to_pool_n'],1)
        self.assertEqual(result['overall_soft_reference_distance_n'],0)


if __name__=='__main__':unittest.main()
