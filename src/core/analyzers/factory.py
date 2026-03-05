"""
Code-Agent — Analyzer Factory.
Returns the correct analyzer for a given file extension.
"""

from pathlib import Path

from src.core.analyzers.base import BaseAnalyzer
from src.core.analyzers.python_analyzer import PythonAnalyzer
from src.core.analyzers.java_analyzer import JavaAnalyzer
from src.core.analyzers.js_ts_analyzer import JavaScriptAnalyzer, TypeScriptAnalyzer

# Registry of all analyzers
_ANALYZERS: list[BaseAnalyzer] = [
    PythonAnalyzer(),
    JavaAnalyzer(),
    JavaScriptAnalyzer(),
    TypeScriptAnalyzer(),
]

# Supported extensions
SUPPORTED_EXTENSIONS = set()
for analyzer in _ANALYZERS:
    SUPPORTED_EXTENSIONS.update(analyzer.extensions)


def get_analyzer(file_path: str) -> BaseAnalyzer | None:
    """Return the appropriate analyzer for the given file, or None if unsupported."""
    for analyzer in _ANALYZERS:
        if analyzer.can_analyze(file_path):
            return analyzer
    return None


def is_supported(file_path: str) -> bool:
    """Check if a file has a supported extension."""
    return Path(file_path).suffix.lower() in SUPPORTED_EXTENSIONS
