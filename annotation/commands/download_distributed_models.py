"""Download exact already-frozen GPU revisions to this machine's HF_HOME."""
import argparse
import json
from pathlib import Path
from huggingface_hub import snapshot_download

p = argparse.ArgumentParser()
p.add_argument('--root', required=True, type=Path)
a = p.parse_args()
models = json.loads((a.root/'heldout_50_evaluation/config/frozen_config.json').read_text())['models']
for name in ('qwen', 'internvl'):
    m = models[name]
    snapshot_download(m['checkpoint'], revision=m['revision'])
