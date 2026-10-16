"""Freeze all representation definitions before any work; never follow main."""
import importlib.metadata
from pathlib import Path
import re

from ataraxia.runtime.config import project_root, resolve_path
from .storage import digest, read, sha, write, atomic_bytes

PACKAGES = ('torch', 'transformers', 'accelerate', 'bitsandbytes', 'numpy',
            'jsonschema', 'pydantic', 'huggingface-hub')


def definitions(root, path):
    config = read(path)
    policy = config['extractor'].get('evidence_policy', 'legacy-model-quotes')
    normalization = config['extractor'].get('normalization_policy')
    if normalization not in (None, 'practical-v1', 'practical-v2-summary'):
        raise ValueError('Unknown normalization policy')
    if normalization and policy != 'deterministic-exact-v1':
        raise ValueError('Practical normalization requires deterministic provenance')
    if policy not in ('legacy-model-quotes', 'deterministic-exact-v1'):
        raise ValueError('Unknown frozen evidence policy')
    if policy == 'deterministic-exact-v1':
        if config['extractor'].get('repair_attempts', 0) or config['extractor'].get('summary_repair_attempts', 0):
            raise ValueError('Deterministic evidence policy does not use GPU evidence repairs')
        if config['schema_version'] != 'semantic-record-v2':
            raise ValueError('Deterministic evidence requires an explicit v2 record schema')
    if config['extractor'].get('summary_repair_attempts', 0) not in (0, 1):
        raise ValueError('Summary repair must be bounded to zero or one attempt')
    for name in ('extractor', 'embedder'):
        if not re.fullmatch(r'[0-9a-f]{40}', config[name]['revision']):
            raise ValueError(f'{name} requires a full immutable 40-character revision')
    if config['memory_mode'] not in ('staged', 'resident'):
        raise ValueError('memory_mode must be staged or resident')
    for key in ('poll_seconds', 'max_attempts', 'retry_base_seconds', 'retry_max_seconds'):
        if config[key] <= 0:
            raise ValueError(f'{key} must be positive')
    for name in ('extractor', 'embedder'):
        if config[name]['batch_size'] <= 0:
            raise ValueError('Batch sizes must be positive')
    if config['extractor']['do_sample'] or config['embedder']['output_dtype'] != 'float32':
        raise ValueError('v1 uses greedy extraction and float32 embedding storage')
    if config['extractor'].get('repair_attempts', 0) not in (0, 1):
        raise ValueError('Only zero or one bounded repair attempt is supported')
    if config['extractor'].get('repair_format', 'full-json') not in ('full-json', 'passage-selector-v1', 'field-passages-v2'):
        raise ValueError('Unknown frozen repair format')
    if config['extractor']['quantization'] != 'nf4-double':
        raise ValueError('v1 extractor must use NF4 double quantization')
    if config['extractor']['checkpoint'] != 'Qwen/Qwen3-4B-Instruct-2507' or config['embedder']['checkpoint'] != 'BAAI/bge-m3':
        raise ValueError('These adapters support the documented Qwen text extractor and BGE-M3 only')
    if config['embedder']['precision'] != 'float16' or config['embedder']['expected_dimensions'] != 1024:
        raise ValueError('BGE-M3 v1 requires float16 inference and 1024 dimensions')
    if config['embedder']['overlength_policy'] != 'fail_no_silent_truncation':
        raise ValueError('Unsupported overlength policy')
    if config['extractor']['max_input_tokens'] <= 0 or config['extractor']['max_new_tokens'] <= 0 or config['embedder']['max_tokens'] <= 0:
        raise ValueError('Token limits must be positive')
    if config['embedder']['max_tokens'] > 8192 or config['extractor']['transcript_max_characters'] < 100:
        raise ValueError('Invalid text budget')
    files = {key:resolve_path(root, config[key]) for key in ('taxonomy', 'prompt', 'template', 'schema', 'record_schema', 'metadata_csv')}
    if policy == 'deterministic-exact-v1':
        schema = read(files['schema'])
        record_schema = read(files['record_schema'])
        if 'unverified_fields' not in schema.get('required', []) or record_schema['properties']['schema_version'].get('const') != 'semantic-record-v2':
            raise ValueError('Deterministic evidence must freeze the matching v2 schemas')
    hashes = {key:sha(value) for key, value in files.items()}
    code = list((Path(__file__).parent).glob('*.py'))
    code += [root/'src/ataraxia/annotation/common.py', root/'src/ataraxia/annotation/prompts.py',
             root/'src/ataraxia/distributed/common.py', root/'src/ataraxia/runtime/config.py',
             root/'semantic_pipeline/scripts/semantic.py', root/'semantic_pipeline/requirements.txt']
    hashes.update({p.relative_to(root).as_posix():sha(p) for p in sorted(code)})
    versions = {name:importlib.metadata.version(name) for name in PACKAGES}
    value = {'config':config, 'definition_hashes':hashes, 'packages':versions}
    value['fingerprint'] = digest(value)
    return value, files


def freeze(root, path, run):
    value, files = definitions(root, path)
    target = run/'frozen.json'
    if target.exists():
        existing = read(target)
        if existing != value:
            raise RuntimeError('Frozen run definitions/packages changed. Restore them or create a NEW run name.')
        for key, source in files.items():
            snap = run/'definitions'/key
            if not snap.is_file() or sha(snap) != value['definition_hashes'][key]:
                raise RuntimeError(f'Frozen snapshot corrupted: {key}')
    else:
        for key, source in files.items():
            atomic_bytes(run/'definitions'/key, source.read_bytes())
        write(target, value)
    return value


def check_freeze(root, path, run, value):
    current, _ = definitions(root, path)
    if current != value or read(run/'frozen.json') != value:
        raise RuntimeError('Run definition changed while running. Stopping; use a new run.')
    for key in ('taxonomy', 'prompt', 'template', 'schema', 'record_schema', 'metadata_csv'):
        if sha(run/'definitions'/key) != value['definition_hashes'][key]:
            raise RuntimeError(f'Frozen snapshot corrupted: {key}')


def root_path():
    return project_root()
