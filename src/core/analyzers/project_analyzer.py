"""
Code-Agent — Project Analyzer Service.
Walks a project directory and analyzes all supported source files.
"""

from pathlib import Path

import structlog

from src.core.analyzers.factory import get_analyzer, is_supported
from src.models.domain import FileAnalysis, ProjectAnalysis

logger = structlog.get_logger()

# Directories to skip
SKIP_DIRS = {
    "__pycache__", ".git", ".svn", ".hg", "node_modules", ".venv", "venv",
    "env", ".env", "dist", "build", ".idea", ".vscode", ".gradle",
    "target", ".mypy_cache", ".pytest_cache", ".tox", "egg-info",
    ".eggs", "site-packages",
}

# Files to skip
SKIP_FILES = {
    "__init__.py", "setup.py", "conftest.py", "manage.py",
}


class ProjectAnalyzerService:
    """Iterates all source files in a project and produces FileAnalysis for each."""

    def analyze_project(
        self,
        project_path: str,
        project_name: str = "",
    ) -> ProjectAnalysis:
        """
        Analyze all supported source files in a project directory.

        Args:
            project_path: Path to the project root.
            project_name: Human-readable name for the project.

        Returns:
            ProjectAnalysis with list of FileAnalysis results.
        """
        root = Path(project_path)
        if not root.is_dir():
            raise ValueError(f"Project path is not a directory: {project_path}")

        if not project_name:
            project_name = root.name

        files: list[FileAnalysis] = []
        languages: dict[str, int] = {}
        total_lines = 0

        log = logger.bind(project=project_name, path=project_path)
        log.info("project_analysis_started")

        for file_path in self._walk_source_files(root):
            analyzer = get_analyzer(str(file_path))
            if not analyzer:
                continue

            try:
                analysis = analyzer.analyze_file(str(file_path), str(root))
                files.append(analysis)
                total_lines += analysis.total_lines

                lang = analysis.language.value
                languages[lang] = languages.get(lang, 0) + 1

            except Exception as e:
                log.warning("file_analysis_failed", file=str(file_path), error=str(e))
                continue

        log.info(
            "project_analysis_completed",
            total_files=len(files),
            total_lines=total_lines,
            languages=languages,
        )

        return ProjectAnalysis(
            project_name=project_name,
            project_path=project_path,
            files=files,
            total_files=len(files),
            total_lines=total_lines,
            languages=languages,
        )

    def _walk_source_files(self, root: Path):
        """Walk directory yielding only supported source files."""
        for item in sorted(root.rglob("*")):
            # Skip directories
            if item.is_dir():
                continue

            # Skip if any parent directory is in SKIP_DIRS
            if any(part in SKIP_DIRS for part in item.relative_to(root).parts):
                continue

            # Skip specific files
            if item.name in SKIP_FILES:
                continue

            # Only supported extensions
            if is_supported(str(item)):
                yield item
