"""Compatibility entry point; implementation moved to ataraxia.datasets.preprocessing."""
import importlib
import runpy
import sys

if __name__ == "__main__":
    runpy.run_module("ataraxia.datasets.preprocessing", run_name="__main__")
else:
    sys.modules[__name__] = importlib.import_module("ataraxia.datasets.preprocessing")
