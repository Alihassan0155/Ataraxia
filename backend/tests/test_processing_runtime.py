import hashlib,json,tempfile,unittest
from pathlib import Path
from backend.processing.runtime import historical_runtime

class RuntimeTests(unittest.TestCase):
    def fixture(self,root):
        annotation=root/'annotation';source=annotation/'semantic_pipeline/runs/semantic_full_v12';source.mkdir(parents=True)
        source.joinpath('frozen.json').write_text(json.dumps({'fingerprint':'a'*64}))
        runtime=root/'backend/reports/processing_launcher'/('runtime_'+'a'*16);runtime.mkdir(parents=True)
        code=b'historical source';runtime.joinpath('worker.py').write_bytes(code)
        runtime.joinpath('runtime_provenance.json').write_text(json.dumps({'frozen_fingerprint':'a'*64,'code_hashes':{'worker.py':hashlib.sha256(code).hexdigest()}}))
        return annotation,runtime
    def test_verified_runtime_is_reused_without_rewriting(self):
        with tempfile.TemporaryDirectory() as d:
            annotation,runtime=self.fixture(Path(d));before=runtime.joinpath('worker.py').stat().st_mtime_ns
            self.assertEqual(historical_runtime(annotation),runtime)
            self.assertEqual(before,runtime.joinpath('worker.py').stat().st_mtime_ns)
    def test_corrupt_recovered_code_is_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            annotation,runtime=self.fixture(Path(d));runtime.joinpath('worker.py').write_text('changed')
            with self.assertRaisesRegex(ValueError,'runtime changed'):historical_runtime(annotation)
