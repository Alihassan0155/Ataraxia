"""Compatibility entry point; implementation moved to ataraxia.research.collection.filter_youtube_english_500."""
import importlib
import runpy
import sys

if __name__ == "__main__":
    runpy.run_module("ataraxia.research.collection.filter_youtube_english_500", run_name="__main__")
else:
    sys.modules[__name__] = importlib.import_module("ataraxia.research.collection.filter_youtube_english_500")
