import sys
from pathlib import Path

_SKILLS = Path(__file__).parent.parent / "skills"

# Make the bundled CLIs importable as `odoo` / `registry` in tests.
sys.path.insert(0, str(_SKILLS / "odoo" / "scripts"))
sys.path.insert(0, str(_SKILLS / "registry" / "scripts"))
