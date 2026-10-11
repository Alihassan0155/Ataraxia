"""Compatibility entry point; implementation moved to ataraxia.evaluation.development.three_human_calibration."""
import importlib
import runpy
import sys

if __name__ == "__main__":
    runpy.run_module("ataraxia.evaluation.development.three_human_calibration", run_name="__main__")
else:
    sys.modules[__name__] = importlib.import_module("ataraxia.evaluation.development.three_human_calibration")
