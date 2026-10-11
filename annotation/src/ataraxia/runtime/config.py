"""Resolve explicit workspace paths without changing the caller's environment."""
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping


def project_root(value=None):
    configured = value or os.environ.get("ATARAXIA_PROJECT_ROOT")
    if configured:
        root = Path(configured).expanduser().resolve()
        if not root.is_dir():
            raise ValueError(f"Project root does not exist: {root}")
        return root
    # Checkout default; installed applications should pass their workspace root.
    for parent in Path(__file__).resolve().parents:
        if (parent/"pyproject.toml").is_file() and (parent/"configs").is_dir():
            return parent
    raise ValueError("Set ATARAXIA_PROJECT_ROOT or supply an explicit workspace root")


def resolve_path(root, value):
    path = Path(value).expanduser()
    return (path if path.is_absolute() else Path(root)/path).resolve()


@dataclass(frozen=True)
class Settings:
    root: Path
    evidence_dir: Path
    output_dir: Path
    environment: Mapping[str, str] = field(repr=False)

    @classmethod
    def load(cls, root=None, environ=None, env_file=None):
        base = project_root(root)
        values = {}
        path = resolve_path(base, env_file) if env_file else base/".env"
        if path.is_file():
            from dotenv import dotenv_values
            values.update({k:v for k,v in dotenv_values(path).items() if v is not None})
        values.update(dict(os.environ if environ is None else environ))
        return cls(base, resolve_path(base, values.get("ATARAXIA_PILOT_DIR", "pilot_50_reels_30h")),
                   resolve_path(base, values.get("ATARAXIA_OUTPUT_ROOT", "runs/annotation")), values)

    def child_environment(self):
        result = dict(self.environment)
        result.update(ATARAXIA_PROJECT_ROOT=str(self.root),
                      ATARAXIA_PILOT_DIR=str(self.evidence_dir),
                      ATARAXIA_OUTPUT_ROOT=str(self.output_dir),
                      PYTHONUTF8="1", PYTHONUNBUFFERED="1")
        src = str(self.root/"src")
        result["PYTHONPATH"] = src + (os.pathsep+result["PYTHONPATH"] if result.get("PYTHONPATH") else "")
        result.setdefault("HF_HOME", str(self.root/".cache/huggingface"))
        return result
