"""Validate the shared environment; optionally cache both official checkpoints."""
from ataraxia.runtime.config import project_root
import argparse
import json
import os
import shutil
from pathlib import Path

BASE = project_root()
os.environ.setdefault("HF_HOME", str(BASE / ".cache/huggingface"))
os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
MODELS = {"qwen": "Qwen/Qwen3-VL-8B-Instruct", "internvl": "OpenGVLab/InternVL3_5-8B-HF"}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--download", action="store_true")
    args = parser.parse_args()
    import torch
    import bitsandbytes
    from transformers import InternVLForConditionalGeneration, Qwen3VLForConditionalGeneration
    assert torch.cuda.is_available(), "CUDA unavailable; check NVIDIA driver and CUDA PyTorch wheel"
    print(json.dumps({"torch": torch.__version__, "bitsandbytes": bitsandbytes.__version__,
          "gpu": torch.cuda.get_device_name(0), "capability": torch.cuda.get_device_capability(0),
          "bf16_supported": torch.cuda.is_bf16_supported(),
          "free_disk_gib": round(shutil.disk_usage(BASE).free / 2**30, 1), "models": MODELS}, indent=2))
    if args.download:
        from huggingface_hub import snapshot_download
        revisions = {}
        for name, model in MODELS.items():
            snapshot = snapshot_download(model, allow_patterns=["*.json", "*.safetensors", "*.model", "*.txt", "*.jinja"], max_workers=2)
            revisions[name] = {"model": model, "revision": Path(snapshot).name}
        target = BASE / ".cache/huggingface/vlm_revisions.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(revisions, indent=2), encoding="utf-8")
        print(f"Checkpoint revisions saved to {target}")


if __name__ == "__main__":
    main()
