"""codeatlas: turn a Python codebase into a queryable knowledge graph."""

from .graph import Atlas
from .scanner import scan_path

__version__ = "0.1.0"
__all__ = ["Atlas", "scan_path", "__version__"]
