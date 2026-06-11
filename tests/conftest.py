import sys
from pathlib import Path

# Make the bundled CLI importable as `odoo` in tests.
sys.path.insert(0, str(Path(__file__).parent.parent / "skills" / "odoo" / "scripts"))
