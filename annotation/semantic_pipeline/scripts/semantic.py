"""Thin checkout launcher; importing it does not start work."""
from pathlib import Path
import sys

if __name__ == '__main__':
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]/'src'))
    from ataraxia.semantic.cli import main
    main()
