"""Active combined Ataraxia dataset; historical snapshots are kept separately."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
METADATA = ROOT / "data/normalized/merged/local_candidates.csv"
AUDIT = ROOT / "data/normalized/audit_merged"
SELECTED = ROOT / "data/normalized/selected_merged_v2"
PREPROCESSED = ROOT / "data/normalized/preprocessed_merged_v2"
HELDOUT = ROOT / "held out/merged_50"
