import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from build_normalized_dataset import MAPPING, youtube_id


class IdentityTests(unittest.TestCase):
    def test_platform_identity_matches_across_url_forms(self):
        video = "--LXDh44cBQ"
        for url in (f"https://youtube.com/shorts/{video}",
                    f"https://youtu.be/{video}?t=3",
                    f"https://youtube.com/watch?v={video}&feature=share"):
            self.assertEqual(youtube_id({"source_url": url}), video)
        self.assertEqual(youtube_id({"video_id": video}), video)

    def test_missing_identity_is_not_guessed_from_legacy_id(self):
        self.assertEqual(youtube_id({"assigned_id": "YT000001"}), "")
        self.assertEqual(youtube_id({"short_url": "https://youtube.com/shorts/invalid"}), "")

    def test_source_categories_share_documented_broad_category(self):
        self.assertEqual(MAPPING["Workout Routines"], MAPPING["fitness"])
        self.assertEqual(MAPPING["Game Commentary"], MAPPING["gaming"])
        self.assertNotIn("Unassigned", MAPPING)


if __name__ == "__main__":
    unittest.main()
