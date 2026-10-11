import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from build_human_fieldwise_consensus import build, EMOTIONS, pearson, ranks, tv_jsd


def annotation(vid="FV000001", **overrides):
    row = {"video_id":vid,"valence":5,"arousal":5,"recovery_suitability":5,
           **{e:0 for e in EMOTIONS},"joy":6,"neutral":4,"dominant_emotion":"joy"}
    row.update(overrides)
    return row


class FieldwiseTests(unittest.TestCase):
    def compare(self, a, b, ids=None):
        with tempfile.TemporaryDirectory() as directory:
            pa, pb = Path(directory)/"a.csv", Path(directory)/"b.txt"
            keys = list(dict.fromkeys(k for r in a for k in r))
            with pa.open("w",newline="") as f:
                writer=csv.DictWriter(f,fieldnames=keys);writer.writeheader();writer.writerows(a)
            pb.write_text(json.dumps(b))
            before=(pa.read_bytes(),pb.read_bytes())
            result=build(ids or ["FV000001"],{"a":pa,"b":pb})
            self.assertEqual(before,(pa.read_bytes(),pb.read_bytes()))
            return result

    def test_one_scalar_dispute_preserves_four_other_fields(self):
        rows,queue,s=self.compare([annotation()],[annotation(arousal=8)])
        r=rows[0]
        self.assertEqual(r["arousal_status"],"needs_adjudication")
        self.assertIsNone(r["consensus_arousal"])
        self.assertEqual(r["consensus_valence"],5)
        self.assertEqual(r["consensus_recovery"],5)
        self.assertEqual(r["dominant_status"],"exact_agreement")
        self.assertEqual(r["emotion_distribution_status"],"pooled")
        self.assertEqual([q["field"] for q in queue],["arousal"])
        self.assertEqual(s["automatic_fields"],4)

    def test_threshold_equality_and_scalar_scale(self):
        rows,queue,_=self.compare([annotation(joy=10,neutral=0,valence=0)],
                                  [annotation(joy=6,neutral=4,valence=2)])
        self.assertEqual(rows[0]["consensus_valence"],1)
        self.assertAlmostEqual(rows[0]["emotion_tv"],.4)
        self.assertEqual(rows[0]["emotion_distribution_status"],"pooled")
        self.assertEqual(queue,[])
        self.assertAlmostEqual(sum(rows[0]["consensus_emotion_distribution"].values()),1)

    def test_declared_tie_disagreement_does_not_discard_distribution(self):
        a=annotation(joy=5,neutral=5)
        rows,queue,_=self.compare([a],[{**a,"dominant_emotion":"neutral"}])
        r=rows[0]
        self.assertEqual(r["dominant_status"],"needs_adjudication")
        self.assertEqual(r["emotion_distribution_status"],"pooled")
        self.assertEqual(r["distribution_derived_dominant_emotions"],["joy","neutral"])
        self.assertEqual([q["field"] for q in queue],["dominant_emotion"])

    def test_bad_scalar_is_local_and_not_dispute(self):
        rows,queue,s=self.compare([annotation(arousal="nan")],[annotation()])
        self.assertEqual(rows[0]["arousal_status"],"invalid")
        self.assertEqual(rows[0]["valence_status"],"pooled")
        self.assertEqual(rows[0]["dominant_status"],"exact_agreement")
        self.assertEqual(s["agreement"]["arousal"]["n"],0)
        self.assertEqual(queue,[])

    def test_bad_emotion_total_does_not_destroy_scalars(self):
        rows,queue,_=self.compare([annotation(joy=5)],[annotation()])
        r=rows[0]
        self.assertEqual(r["emotion_distribution_status"],"invalid")
        self.assertEqual(r["dominant_status"],"invalid")
        self.assertEqual(r["valence_status"],"pooled")
        self.assertEqual(queue,[])

    def test_ids_duplicates_and_missing_never_guess(self):
        rows,queue,s=self.compare([annotation(),annotation(),annotation("FV000037"),annotation("bad")],
                                  [annotation()],ids=["FV000001","FV000131"])
        self.assertEqual(rows[0]["valence_status"],"invalid")
        self.assertEqual(rows[1]["valence_status"],"missing")
        self.assertEqual(s["source_validation"]["a"]["unexpected_ids"],["FV000037"])
        self.assertEqual({x["kind"] for x in s["source_validation"]["a"]["issues"]},
                         {"malformed_id","unexpected_id","duplicate_id"})
        self.assertEqual(queue,[])

    def test_distances_and_tied_ranks_have_known_values(self):
        a={e:0 for e in EMOTIONS};b=a.copy();a["joy"]=1;b["neutral"]=1
        self.assertEqual(tv_jsd(a,b),(1,1))
        self.assertEqual(tv_jsd(a,a),(0,0))
        self.assertEqual(ranks([5,1,1,3]),[4,1.5,1.5,3])
        self.assertAlmostEqual(pearson([1,2,3],[3,2,1]),-1)
        self.assertIsNone(pearson([1,1],[2,3]))


if __name__ == "__main__":
    unittest.main()
