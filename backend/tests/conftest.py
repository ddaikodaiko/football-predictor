import sys
from pathlib import Path

# Tests import backend modules the same way api.py does: as top-level modules.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
