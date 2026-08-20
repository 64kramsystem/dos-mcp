"""DOSBox-X tools for DOS malware analysis."""

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _installed_version

__all__ = ["__version__"]

try:
    __version__ = _installed_version("dos-mcp")
except PackageNotFoundError:  # pragma: no cover - bare checkout
    __version__ = "0.0.0+unknown"

