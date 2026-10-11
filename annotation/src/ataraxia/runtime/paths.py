"""Worker paths are process-local and configured before model modules load."""
import os
from .config import project_root, resolve_path


def evidence_root():
    return resolve_path(project_root(), os.environ.get("ATARAXIA_PILOT_DIR", "pilot_50_reels_30h"))


def metadata_path():
    return resolve_path(project_root(), os.environ["ATARAXIA_METADATA_PATH"]) if os.environ.get(
        "ATARAXIA_METADATA_PATH") else evidence_root()/"pilot_metadata.csv"


def expected_video_count():
    count = int(os.environ.get("ATARAXIA_EXPECTED_VIDEO_COUNT", "50"))
    if count <= 0:
        raise ValueError("Expected video count must be positive")
    return count
