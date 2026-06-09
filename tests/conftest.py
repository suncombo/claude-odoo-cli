import sys
from pathlib import Path

# Make scripts/odoo.py importable as `odoo` in tests.
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
