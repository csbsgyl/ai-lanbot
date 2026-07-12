from pathlib import Path
import sys


PLUGIN_ROOT = Path(__file__).resolve().parents[3] / 'bundled_plugins' / 'idc_query'
sys.path.insert(0, str(PLUGIN_ROOT))
