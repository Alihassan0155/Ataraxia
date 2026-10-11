"""Compatibility entry point; implementation moved to ataraxia.annotation.diagnostics."""
import importlib
import runpy
import sys

if __name__ == "__main__":
    runpy.run_module("ataraxia.annotation.diagnostics", run_name="__main__")
else:
    sys.modules[__name__] = importlib.import_module("ataraxia.annotation.diagnostics")
