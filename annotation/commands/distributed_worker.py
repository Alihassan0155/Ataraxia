"""Can be copied alone to local disk if Python cannot launch a UNC script."""
import sys
from pathlib import Path

root = Path(sys.argv[sys.argv.index('--root')+1])
sys.path.insert(0, str(root/'src'))
from ataraxia.distributed.worker import main

if __name__ == '__main__':
    main()
