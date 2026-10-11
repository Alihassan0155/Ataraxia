"""Compatibility entry point; implementation moved to ataraxia.evaluation.development.model_comparison."""
import importlib
import runpy
import sys

if __name__ == "__main__":
    runpy.run_module("ataraxia.evaluation.development.model_comparison", run_name="__main__")
else:
    sys.modules[__name__] = importlib.import_module("ataraxia.evaluation.development.model_comparison")
