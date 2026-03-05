"""
Code-Agent — Base Analyzer.
Abstract base class for all language-specific analyzers.
"""

from abc import ABC, abstractmethod
from pathlib import Path

from src.models.domain import FileAnalysis, LanguageType


class BaseAnalyzer(ABC):
    """Base class for language-specific code analyzers."""

    @property
    @abstractmethod
    def language(self) -> LanguageType:
        """The programming language this analyzer handles."""
        ...

    @property
    @abstractmethod
    def extensions(self) -> list[str]:
        """File extensions this analyzer handles (e.g., ['.py'])."""
        ...

    def can_analyze(self, file_path: str) -> bool:
        """Check if this analyzer can handle the given file."""
        return Path(file_path).suffix.lower() in self.extensions

    @abstractmethod
    def analyze_file(self, file_path: str, project_root: str = "") -> FileAnalysis:
        """
        Analyze a single source file and return structured analysis.

        Args:
            file_path: Absolute path to the file.
            project_root: Root path of the project (for relative path calculation).

        Returns:
            FileAnalysis with extracted metadata.
        """
        ...

    def _read_file(self, file_path: str) -> str:
        """Read file content with encoding fallback."""
        for encoding in ("utf-8", "latin-1", "cp1252"):
            try:
                with open(file_path, "r", encoding=encoding) as f:
                    return f.read()
            except UnicodeDecodeError:
                continue
        return ""

    def _relative_path(self, file_path: str, project_root: str) -> str:
        """Get relative path from project root."""
        try:
            return str(Path(file_path).relative_to(project_root))
        except ValueError:
            return file_path
