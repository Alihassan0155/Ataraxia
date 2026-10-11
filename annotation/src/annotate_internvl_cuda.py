"""Compatibility entry point; implementation moved to ataraxia.research.pipelines.internvl_cuda."""
import importlib
import runpy
import sys

if __name__ == "__main__":
    runpy.run_module("ataraxia.research.pipelines.internvl_cuda", run_name="__main__")
else:
    sys.modules[__name__] = importlib.import_module("ataraxia.research.pipelines.internvl_cuda")
