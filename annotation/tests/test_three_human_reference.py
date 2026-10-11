"""Tests for three-rater coverage and preservation of independent fields."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from build_three_human_reference import build


def annotation(vid,value=5):
    return {'video_id':vid,'valence':value,'arousal':value,'recovery_suitability':value,
            'joy':10,'sadness':0,'anger':0,'fear_anxiety':0,'surprise':0,
            'disgust':0,'calm_contentment':0,'neutral':0,'dominant_emotion':'joy'}


class ThreeHumanReferenceTests(unittest.TestCase):
    def run_fixture(self,data):
        with tempfile.TemporaryDirectory() as directory:
            sources={}
            for name,rows in data.items():
                path=Path(directory)/(name+'.json');path.write_text(json.dumps(rows),encoding='utf-8');sources[name]=path
            return build(['FV000001'],sources)

    def test_third_annotator_changes_mean_and_uncertainty(self):
        rows,_,_=self.run_fixture({h:[annotation('FV000001',v)] for h,v in [('ali',0),('ghayas',3),('zara',9)]})
        row=rows[0]
        self.assertEqual(row['valence_human_mean'],4)
        self.assertEqual(row['valence_uncertainty'],6)
        self.assertAlmostEqual(row['valence_human_mean_model_scale'],-.2)

    def test_bad_distribution_keeps_scalars_and_raw_values(self):
        bad=annotation('FV000001');bad['joy']=9
        rows,_,_=self.run_fixture({'ali':[bad],'ghayas':[annotation('FV000001')],'zara':[annotation('FV000001')]})
        self.assertEqual(rows[0]['valence_human_mean'],5)
        self.assertIsNone(rows[0]['pooled_emotion_distribution'])
        self.assertEqual(rows[0]['human_ali_raw_annotations']['joy'],9)

    def test_no_silent_two_rater_fallback(self):
        rows,_,_=self.run_fixture({'ali':[],'ghayas':[annotation('FV000001')],'zara':[annotation('FV000001')]})
        self.assertIsNone(rows[0]['valence_human_mean'])
        self.assertIsNone(rows[0]['pooled_emotion_distribution'])

    def test_missing_dominant_preserves_numeric_uncertainty(self):
        data={h:[annotation('FV000001')] for h in ['ali','ghayas','zara']}
        data['ali'][0]['dominant_emotion']=None
        rows,_,_=self.run_fixture(data)
        self.assertEqual(rows[0]['overall_human_uncertainty'],0)
        self.assertIsNone(rows[0]['all_three_dominant_agree'])
        self.assertEqual(rows[0]['pooled_distribution_dominant'],'joy')


if __name__=='__main__':unittest.main()
