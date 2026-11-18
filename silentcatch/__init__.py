"""silentcatch: find exception handlers that swallow failures."""

from .detector import Finding, Verdict, analyse_file, analyse_source

__version__ = "0.1.0"
__all__ = ["Finding", "Verdict", "analyse_file", "analyse_source"]