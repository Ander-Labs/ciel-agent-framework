from importlib.metadata import version as _pkg_version, PackageNotFoundError

try:
    __version__ = _pkg_version("ciel")
except PackageNotFoundError:  # pragma: no cover
    __version__ = "0.1.0"

from ciel.security import ApprovalPolicy

__all__ = ["__version__", "ApprovalPolicy"]
