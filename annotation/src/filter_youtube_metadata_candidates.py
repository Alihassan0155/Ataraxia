"""Compatibility entry point; implementation moved to ataraxia.research.collection.filter_youtube_metadata_candidates."""
import importlib
import runpy
import sys

if __name__ == "__main__":
    runpy.run_module("ataraxia.research.collection.filter_youtube_metadata_candidates", run_name="__main__")
else:
    sys.modules[__name__] = importlib.import_module("ataraxia.research.collection.filter_youtube_metadata_candidates")
