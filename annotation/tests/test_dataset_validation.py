import sys
import unittest
import tempfile
import wave
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from validate_normalized_dataset import language_decision, decode_mono_audio


class LanguageRulesTests(unittest.TestCase):
    def window(self, language, probability=.95, characters=20):
        return {"language": language, "probability": probability, "speech_characters": characters}

    def test_all_clip_windows_influence_decision(self):
        self.assertEqual(language_decision([self.window("en"), self.window("es")]), "review_mixed_language")
        self.assertEqual(language_decision([self.window("en"), self.window("ur")]), "review_mixed_language")

    def test_uncertainty_and_speechless_are_reviewed(self):
        self.assertEqual(language_decision([self.window("en", .5)]), "review_low_confidence")
        self.assertEqual(language_decision([self.window("es", characters=0)]), "review_no_detected_speech")
        self.assertEqual(language_decision([]), "review_no_detected_speech")

    def test_non_target_is_not_silently_deleted(self):
        self.assertEqual(language_decision([self.window("es")]), "review_non_target_language")
        self.assertEqual(language_decision([self.window("en")]), "target_language_candidate")

    def test_real_stereo_audio_resampling_preserves_duration_and_signal(self):
        import numpy as np
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "stereo.wav"
            tone = (10000 * np.sin(2 * np.pi * 440 * np.arange(48000) / 48000)).astype(np.int16)
            with wave.open(str(path), "wb") as handle:
                handle.setnchannels(2)
                handle.setsampwidth(2)
                handle.setframerate(48000)
                handle.writeframes(np.column_stack((tone, tone)).tobytes())
            result = decode_mono_audio(path)
            self.assertEqual(result.dtype, np.float32)
            self.assertEqual(result.ndim, 1)
            self.assertAlmostEqual(len(result) / 16000, 1, places=3)
            self.assertTrue(np.isfinite(result).all())
            self.assertGreater(float(np.std(result)), .1)


if __name__ == "__main__":
    unittest.main()
