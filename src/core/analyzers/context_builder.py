"""
Code-Agent — Context Builder.
Builds a ProjectContext (dependency graph + module map) from Pass 1 results.
This is 100 % deterministic — no LLM calls.
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import PurePosixPath

import structlog

from src.models.domain import (
    ArchivoFuente,
    FileContext,
    ProjectAnalysis,
    ProjectContext,
    ProjectManifest,
    UnidadLogica,
)

logger = structlog.get_logger()

# ── Module-purpose heuristics ────────────────────────────────────────
_MODULE_PURPOSE_KEYWORDS: dict[str, str] = {
    "auth": "Autenticación y autorización",
    "login": "Autenticación y autorización",
    "security": "Seguridad y control de acceso",
    "card": "Gestión de tarjetas",
    "tarjeta": "Gestión de tarjetas",
    "transaction": "Procesamiento de transacciones",
    "transaccion": "Procesamiento de transacciones",
    "payment": "Procesamiento de pagos",
    "pago": "Procesamiento de pagos",
    "user": "Gestión de usuarios",
    "usuario": "Gestión de usuarios",
    "config": "Configuración del sistema",
    "common": "Utilidades compartidas",
    "util": "Utilidades compartidas",
    "model": "Modelos de datos",
    "dto": "Objetos de transferencia de datos",
    "repository": "Acceso a datos",
    "service": "Lógica de negocio",
    "controller": "Controladores REST / API",
    "adapter": "Adaptadores de integración",
    "integration": "Integraciones externas",
    "api": "Capa API / REST",
    "db": "Capa de base de datos",
    "core": "Núcleo de la aplicación",
}


class ContextBuilder:
    """
    Builds a ``ProjectContext`` from the structural results of Pass 1.

    Usage::

        builder = ContextBuilder()
        ctx = builder.build(project_analysis, archivos, unidades)
    """

    # ── public ────────────────────────────────────────────────────────

    def build(
        self,
        project_analysis: ProjectAnalysis,
        archivos: list[ArchivoFuente],
        unidades: list[UnidadLogica],
    ) -> ProjectContext:
        """
        Build the full project context.

        Args:
            project_analysis: Raw analysis from ProjectAnalyzerService.
            archivos: ArchivoFuente list produced by Pass 1.
            unidades: UnidadLogica list produced by Pass 1.

        Returns:
            ProjectContext ready to be consumed by the LLM enricher.
        """
        log = logger.bind(project=project_analysis.project_name)
        log.info("context_builder_started", files=len(archivos))

        # 1. Build lookup: file_path → FileAnalysis
        fa_by_path: dict[str, object] = {
            fa.file_path: fa for fa in project_analysis.files
        }

        # 2. Build import graph  (file_path → set of imported module names)
        import_graph: dict[str, set[str]] = {}
        for fa in project_analysis.files:
            import_graph[fa.file_path] = set(fa.imports)

        # 3. Resolve imports to project files (best-effort matching)
        deps, reverse_deps = self._resolve_dependencies(
            import_graph, list(fa_by_path.keys())
        )

        # 4. Build module map  (module_name → list of file_paths)
        module_map = self._build_module_map(list(fa_by_path.keys()))

        # 5. Layer counts from archivos
        layer_counts: dict[str, int] = defaultdict(int)
        for a in archivos:
            if a.capa:
                layer_counts[a.capa] += 1

        # 6. Build manifest
        manifest = ProjectManifest(
            project_name=project_analysis.project_name,
            total_files=project_analysis.total_files,
            total_lines=project_analysis.total_lines,
            layers=dict(layer_counts),
            languages=project_analysis.languages,
            modules=sorted(module_map.keys()),
        )

        # 7. Build per-file contexts
        archivo_layer: dict[str, str] = {a.ruta_archivo or a.nombre: a.capa or "" for a in archivos}

        file_contexts: dict[str, FileContext] = {}
        for fp in fa_by_path:
            module = self._module_for_path(fp, module_map)
            siblings = [
                s for s in module_map.get(module, []) if s != fp
            ]
            fc = FileContext(
                file_path=fp,
                file_name=PurePosixPath(fp).name,
                module=module,
                layer=archivo_layer.get(fp),
                imports_from=sorted(deps.get(fp, [])),
                imported_by=sorted(reverse_deps.get(fp, [])),
                sibling_files=sorted(siblings),
                module_purpose=self._infer_module_purpose(module),
            )
            file_contexts[fp] = fc

        ctx = ProjectContext(manifest=manifest, file_contexts=file_contexts)
        log.info(
            "context_builder_completed",
            modules=len(module_map),
            edges=sum(len(v) for v in deps.values()),
        )
        return ctx

    # ── private helpers ───────────────────────────────────────────────

    def _resolve_dependencies(
        self,
        import_graph: dict[str, set[str]],
        project_files: list[str],
    ) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
        """
        Match import names to actual project file paths.

        Strategy: for each import ``x.y.z``, check whether any project file
        path contains ``x/y/z`` or ends with ``z.py`` / ``z.java``, etc.
        This is best-effort — external dependencies are silently ignored.

        Returns:
            (deps, reverse_deps) — both keyed by file_path.
        """
        # Build quick lookup: last component of path → full path(s)
        name_to_paths: dict[str, list[str]] = defaultdict(list)
        for fp in project_files:
            stem = PurePosixPath(fp).stem  # e.g. "pipeline"
            name_to_paths[stem.lower()].append(fp)

        deps: dict[str, list[str]] = defaultdict(list)
        reverse_deps: dict[str, list[str]] = defaultdict(list)

        for source_file, imports in import_graph.items():
            for imp in imports:
                # Extract the last segment: "src.core.analyzers.pipeline" → "pipeline"
                last_segment = imp.rsplit(".", 1)[-1].lower()
                # Also try the full dotted path converted to path-like
                dotted_path = imp.replace(".", "/").lower()

                matched_files: list[str] = []

                # Strategy A: exact stem match
                if last_segment in name_to_paths:
                    for candidate in name_to_paths[last_segment]:
                        if candidate != source_file:
                            matched_files.append(candidate)

                # Strategy B: path substring match (for nested modules)
                if not matched_files:
                    for candidate in project_files:
                        if (
                            candidate != source_file
                            and dotted_path in candidate.replace("\\", "/").lower()
                        ):
                            matched_files.append(candidate)

                for mf in matched_files:
                    if mf not in deps[source_file]:
                        deps[source_file].append(mf)
                    if source_file not in reverse_deps[mf]:
                        reverse_deps[mf].append(source_file)

        return dict(deps), dict(reverse_deps)

    @staticmethod
    def _build_module_map(file_paths: list[str]) -> dict[str, list[str]]:
        """
        Group files by their immediate parent directory (≈ module / package).

        ``src/core/analyzers/pipeline.py`` → module ``analyzers``
        """
        module_map: dict[str, list[str]] = defaultdict(list)
        for fp in file_paths:
            parts = PurePosixPath(fp).parts
            # Use the immediate parent dir as the module name
            if len(parts) >= 2:
                module = parts[-2]
            else:
                module = "_root"
            module_map[module].append(fp)
        return dict(module_map)

    @staticmethod
    def _module_for_path(
        file_path: str, module_map: dict[str, list[str]]
    ) -> str:
        """Return the module name that contains ``file_path``."""
        for mod, files in module_map.items():
            if file_path in files:
                return mod
        return "_unknown"

    @staticmethod
    def _infer_module_purpose(module_name: str) -> str:
        """
        Infer a human-readable purpose for a module based on naming heuristics.
        """
        lower = module_name.lower()
        for keyword, purpose in _MODULE_PURPOSE_KEYWORDS.items():
            if keyword in lower:
                return purpose
        return f"Módulo {module_name}"
