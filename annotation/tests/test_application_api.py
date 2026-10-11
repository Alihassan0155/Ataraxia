"""Safe refactor contracts: no model inference, network, or research writes."""
import ast
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from ataraxia.api import AnnotationJob, prepare_job, run_annotation
from ataraxia.runtime.config import Settings

ROOT = Path(__file__).resolve().parents[1]


class ApplicationApiTests(unittest.TestCase):
    def workspace(self, base):
        evidence = base/'evidence'
        (evidence/'videos').mkdir(parents=True)
        (evidence/'context').mkdir()
        (evidence/'videos/V1.mp4').write_bytes(b'not decoded in dry run')
        (evidence/'context/V1.json').write_text('{}')
        (evidence/'pilot_metadata.csv').write_text('assigned_id,duration\nV1,1\n')
        return evidence

    def test_settings_do_not_mutate_environment_or_expose_keys(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            (base/'.env').write_text('GEMINI_API_KEYS=dummy-test-key\nATARAXIA_OUTPUT_ROOT=runs/custom\n')
            before = dict(os.environ)
            settings = Settings.load(base, environ={'ATARAXIA_OUTPUT_ROOT':'runs/override'})
            self.assertEqual(settings.output_dir, base/'runs/override')
            self.assertNotIn('dummy-test-key', repr(settings))
            self.assertEqual(dict(os.environ), before)

    def test_worker_paths_and_cardinality_are_explicit(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            evidence = self.workspace(base)
            settings = Settings.load(base, environ={})
            job = AnnotationJob('qwen', evidence, Path('runs/new'), options=('--phase','pilot'))
            command, env, output = prepare_job(job, settings)
            self.assertEqual(env['ATARAXIA_EXPECTED_VIDEO_COUNT'], '1')
            self.assertEqual(output, base/'runs/new')
            self.assertIn('ataraxia.annotation.backends.qwen', command)
            self.assertFalse(output.exists())
            with self.assertRaises(ValueError):
                prepare_job(AnnotationJob('qwen', evidence, Path('runs/new'),
                    options=('--phase','pilot','--run-d','data/overwrite')), settings)
            with patch('ataraxia.api.subprocess.run') as worker:
                worker.return_value.returncode = 7
                result = run_annotation(job, settings)
                self.assertEqual(result.returncode, 7)
                self.assertEqual(worker.call_args.kwargs['env']['ATARAXIA_PILOT_DIR'], str(evidence))

    def test_research_outputs_and_bad_ids_are_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            evidence = self.workspace(base)
            settings = Settings.load(base, environ={})
            with self.assertRaises(ValueError):
                prepare_job(AnnotationJob('gemini', evidence, base/'data/output'), settings)
            (evidence/'pilot_metadata.csv').write_text('assigned_id,duration\n../V1,1\n')
            with self.assertRaises(ValueError):
                prepare_job(AnnotationJob('gemini', evidence, base/'runs/new'), settings)

    def test_native_inference_helpers_match_frozen_sources(self):
        def funcs(path):
            return {n.name:ast.dump(n, include_attributes=False)
                    for n in ast.parse(path.read_text(encoding='utf-8')).body
                    if isinstance(n, ast.FunctionDef) and n.name != 'main'}
        for old, new in [('annotate_qwen_cuda','qwen'),('annotate_internvl_cuda','internvl'),('schema_repair','schema_repair')]:
            before = funcs(ROOT/'heldout_50_evaluation/components'/f'{old}.py')
            after = funcs(ROOT/'src/ataraxia/annotation/backends'/f'{new}.py')
            self.assertEqual(before, after)

    def test_prompt_strings_are_identical_to_pre_refactor(self):
        def strings(path):
            return [n.value for n in ast.walk(ast.parse(path.read_text(encoding='utf-8')))
                    if isinstance(n, ast.Constant) and isinstance(n.value, str)]
        self.assertEqual(strings(ROOT/'research/migration/source_snapshots/prompts.py'),
                         strings(ROOT/'src/ataraxia/annotation/prompts.py'))

    def test_application_gemini_failover_preserves_same_video(self):
        from ataraxia.annotation.backends import gemini_execution as worker
        calls = []
        def attempt(keys, video_id, index, disabled, config, **kwargs):
            calls.append((video_id, index))
            if index == 0:
                raise TimeoutError('synthetic stalled request')
            return {'video_id': video_id}, index
        with patch.object(worker, 'append'):
            result, index = worker.rotating_video(['dummy-a','dummy-b'], 'V1', 0, set(), {}, attempt)
        self.assertEqual(calls, [('V1',0),('V1',1)])
        self.assertEqual(result['video_id'], 'V1')
        self.assertEqual(index, 1)


if __name__ == '__main__':
    unittest.main()
