"""Local, evidence-first multi-engine RAW benchmark (not a quality oracle)."""
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'benchmark' / 'python-deps'))
