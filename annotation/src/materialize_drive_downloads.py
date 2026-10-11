"""Compatibility entry point; implementation moved to ataraxia.research.collection.materialize_drive_downloads."""
import importlib
import runpy
import sys

if __name__ == "__main__":
    runpy.run_module("ataraxia.research.collection.materialize_drive_downloads", run_name="__main__")
else:
    sys.modules[__name__] = importlib.import_module("ataraxia.research.collection.materialize_drive_downloads")
