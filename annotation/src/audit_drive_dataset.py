"""Compatibility entry point; implementation moved to ataraxia.research.collection.audit_drive_dataset."""
import importlib
import runpy
import sys

if __name__ == "__main__":
    runpy.run_module("ataraxia.research.collection.audit_drive_dataset", run_name="__main__")
else:
    sys.modules[__name__] = importlib.import_module("ataraxia.research.collection.audit_drive_dataset")
