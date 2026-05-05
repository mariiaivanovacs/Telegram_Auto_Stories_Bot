import sys
from pathlib import Path

# Ensure project root is on the path so `src.*` imports work from any CWD
sys.path.insert(0, str(Path(__file__).resolve().parent))
