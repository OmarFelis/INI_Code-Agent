"""
Code-Agent — Worker Pool.
Provides parallel execution for the 2-pass pipeline using asyncio.
"""

from __future__ import annotations

import asyncio
import json
import os
from typing import Callable

import structlog

from src.core.analyzers import logical_unit_extractor
from src.models.domain import (
    ArchivoFuente,
    FileAnalysis,
    ProjectContext,
    UnidadLogica,
)

logger = structlog.get_logger()

# Default concurrency limits
_DEFAULT_AST_WORKERS = min(os.cpu_count() * 2 if os.cpu_count() else 4, 20)
_DEFAULT_LLM_WORKERS = 5


# ── Pass 1: Parallel Structural Extraction ───────────────────────────

async def run_parallel_extraction(
    files: list[FileAnalysis],
    project_path: str,
    activo_id: str,
    aplicacion_id: str,
    max_workers: int | None = None,
    on_progress: Callable[[int, int, str], None] | None = None,
) -> tuple[list[ArchivoFuente], list[UnidadLogica], list[dict]]:
    """
    Run logical_unit_extractor.extract() in parallel for all files.

    Args:
        files: List of FileAnalysis from ProjectAnalyzerService.
        project_path: Root path of the project.
        activo_id: UUID of the asset.
        aplicacion_id: UUID of the application.
        max_workers: Max concurrent extractions (default: CPU × 2, max 20).
        on_progress: Optional callback(processed, total, file_name).

    Returns:
        Tuple of (archivos, unidades, failed_files).
    """
    workers = max_workers or _DEFAULT_AST_WORKERS
    semaphore = asyncio.Semaphore(workers)
    total = len(files)

    archivos: list[ArchivoFuente] = []
    unidades: list[UnidadLogica] = []
    failed_files: list[dict] = []
    processed = 0
    lock = asyncio.Lock()

    log = logger.bind(total_files=total, workers=workers)
    log.info("parallel_extraction_started")

    async def _extract_one(file_analysis: FileAnalysis) -> None:
        nonlocal processed
        async with semaphore:
            try:
                from pathlib import Path
                file_abs_path = str(Path(project_path) / file_analysis.file_path)

                # Run the CPU-bound extraction in a thread
                archivo, file_unidades = await asyncio.to_thread(
                    logical_unit_extractor.extract,
                    file_analysis=file_analysis,
                    file_path_absolute=file_abs_path,
                    activo_id=activo_id,
                    aplicacion_id=aplicacion_id,
                )

                async with lock:
                    archivos.append(archivo)
                    unidades.extend(file_unidades)
                    processed += 1

                if on_progress:
                    on_progress(processed, total, archivo.nombre)

            except Exception as e:
                async with lock:
                    failed_files.append({
                        "archivo": file_analysis.file_name,
                        "error": str(e),
                    })
                    processed += 1
                logger.error(
                    "parallel_extraction_file_failed",
                    file=file_analysis.file_name,
                    error=str(e),
                )

    # Launch all tasks with controlled concurrency
    tasks = [_extract_one(fa) for fa in files]
    await asyncio.gather(*tasks)

    log.info(
        "parallel_extraction_completed",
        processed=len(archivos),
        failed=len(failed_files),
    )
    return archivos, unidades, failed_files


# ── Pass 2: Parallel LLM Enrichment with Context ────────────────────

async def run_parallel_enrichment(
    archivos: list[ArchivoFuente],
    project_context: ProjectContext,
    max_workers: int | None = None,
) -> list[dict]:
    """
    Run LLM enrichment in parallel for files that have context,
    prioritising DOMINIO-layer files.

    This function builds the enrichment payloads with context and
    delegates to the llm_enricher.  It returns the raw enrichment
    results so the caller can merge them into the scan data.

    Args:
        archivos: ArchivoFuente list from Pass 1.
        project_context: ProjectContext built by ContextBuilder.
        max_workers: Max concurrent LLM calls.

    Returns:
        List of dicts with enrichment data per file.
    """
    from src.core.enricher import llm_enricher

    workers = max_workers or _DEFAULT_LLM_WORKERS
    semaphore = asyncio.Semaphore(workers)

    log = logger.bind(total_files=len(archivos), workers=workers)
    log.info("parallel_enrichment_started")

    manifest = project_context.manifest

    async def _enrich_one(archivo: ArchivoFuente) -> dict:
        async with semaphore:
            file_ctx = project_context.file_contexts.get(
                archivo.ruta_archivo or archivo.nombre
            )

            # Build context-enhanced payload
            context_block = _build_context_block(manifest, file_ctx)

            payload = {
                "nombre_archivo": archivo.nombre,
                "ruta_archivo": archivo.ruta_archivo,
                "lenguaje": archivo.lenguaje or "Desconocido",
                "capa": archivo.capa or "Sin clasificar",
                "contexto_proyecto": context_block,
                # codigo_completo is NOT available here — it will be read
                # from disk by the enricher route if needed
            }

            return payload

    # Build payloads (no LLM call yet — this is fast)
    payloads = []
    for archivo in archivos:
        payload = await _enrich_one(archivo)
        payloads.append(payload)

    log.info("parallel_enrichment_payloads_built", count=len(payloads))
    return payloads


# ── Helpers ──────────────────────────────────────────────────────────

def _build_context_block(
    manifest,
    file_ctx,
) -> str:
    """
    Build a human-readable context string for the LLM prompt.
    """
    lines: list[str] = []

    # Project-level context
    lines.append(f"PROYECTO: {manifest.project_name}")
    lines.append(
        f"  Arquitectura: {manifest.total_files} archivos, "
        + ", ".join(f"{v} {k}" for k, v in manifest.layers.items())
    )
    lines.append(
        f"  Lenguajes: "
        + ", ".join(f"{k}: {v}" for k, v in manifest.languages.items())
    )
    if manifest.modules:
        lines.append(f"  Módulos: {', '.join(manifest.modules)}")

    # File-level context
    if file_ctx:
        lines.append("")
        lines.append(f"ARCHIVO: {file_ctx.file_name}")
        lines.append(f"  Módulo: {file_ctx.module} ({file_ctx.module_purpose})")
        if file_ctx.layer:
            lines.append(f"  Capa: {file_ctx.layer}")
        if file_ctx.imports_from:
            lines.append(
                f"  Depende de: {', '.join(file_ctx.imports_from[:5])}"
            )
        if file_ctx.imported_by:
            lines.append(
                f"  Usado por: {', '.join(file_ctx.imported_by[:5])}"
            )
        if file_ctx.sibling_files:
            lines.append(
                f"  Hermanos en módulo: {', '.join(file_ctx.sibling_files[:5])}"
            )

    return "\n".join(lines)
