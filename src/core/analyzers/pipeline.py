"""
Code-Agent — Pipeline Orchestrator V2.
Coordinates the full scan flow with parallel workers and context-aware analysis:
  Pass 1.  Parallel AST extraction  (worker_pool)
  Bridge.  Build dependency graph    (context_builder)
  Pass 2.  LLM enrichment w/ context (worker_pool + llm_enricher)  — opt-in
  Final.   Aggregation + persistence
"""

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import structlog

from src.config import settings
from src.core.analyzers.context_builder import ContextBuilder
from src.core.analyzers.project_analyzer import ProjectAnalyzerService
from src.core.analyzers import logical_unit_extractor, worker_pool
from src.integrations.aone_client import AOneClient
from src.models.domain import (
    ArchivoFuente,
    UnidadLogica,
    Escaneo,
    ProjectContext,
    RiskLevel,
)

logger = structlog.get_logger()


class PipelineResult:
    """Result of a pipeline execution."""

    def __init__(self):
        self.archivos: list[ArchivoFuente] = []
        self.unidades: list[UnidadLogica] = []
        self.total_files: int = 0
        self.processed_files: int = 0
        self.failed_files: list[dict] = []
        self.scan_id: str | None = None
        self.score_general: float = 0.0
        self.nivel_riesgo: str = "LOW"
        self.project_context: ProjectContext | None = None


async def run(
    project_path: str,
    activo_id: str,
    aplicacion_id: str,
    microservice_name: str,
    aone_client: AOneClient | None = None,
    on_file_processed: callable = None,
) -> PipelineResult:
    """
    Execute the full scan pipeline (V2 — parallel + context-aware).

    Args:
        project_path: Local path to the repository.
        activo_id: UUID of the asset in infra.activos.
        aplicacion_id: UUID of the app in producto.aplicaciones.
        microservice_name: Human-readable name.
        aone_client: Optional A-ONE HTTP client for persistence.
        on_file_processed: Optional callback(processed, total, file_name) for progress.

    Returns:
        PipelineResult with all extracted data and project context.
    """
    log = logger.bind(microservice=microservice_name, path=project_path)
    result = PipelineResult()

    # ── 1. Analyze project (file discovery + AST parsing) ─────────
    log.info("pipeline_phase1_analyze_start")
    analyzer_service = ProjectAnalyzerService()
    project = analyzer_service.analyze_project(project_path, microservice_name)
    result.total_files = project.total_files

    log.info("pipeline_phase1_analyze_done", files=project.total_files, lines=project.total_lines)

    # ── 2. Get commit hash ────────────────────────────────────────
    commit_hash = _get_commit_hash(project_path)

    # ── 3. PASS 1: Parallel extraction ────────────────────────────
    log.info(
        "pipeline_pass1_parallel_start",
        workers=settings.parallel_workers_ast,
    )

    archivos, unidades, failed_files = await worker_pool.run_parallel_extraction(
        files=project.files,
        project_path=project_path,
        activo_id=activo_id,
        aplicacion_id=aplicacion_id,
        max_workers=settings.parallel_workers_ast,
        on_progress=on_file_processed,
    )

    # Set commit hash and timestamp on all archivos
    for archivo in archivos:
        archivo.commit_hash = commit_hash
        archivo.escaneado_en = datetime.now(timezone.utc).isoformat()

    result.archivos = archivos
    result.unidades = unidades
    result.processed_files = len(archivos)
    result.failed_files = failed_files

    log.info(
        "pipeline_pass1_parallel_done",
        processed=len(archivos),
        failed=len(failed_files),
    )

    # ── 4. CONTEXT BUILDER: dependency graph ──────────────────────
    if settings.enable_context_enrichment:
        log.info("pipeline_context_builder_start")
        builder = ContextBuilder()
        project_context = builder.build(project, archivos, unidades)
        result.project_context = project_context
        log.info(
            "pipeline_context_builder_done",
            modules=len(project_context.manifest.modules),
        )

    # ── 5. Persist archivos + unidades to A-ONE ───────────────────
    if aone_client:
        for archivo in archivos:
            try:
                resp = await aone_client.post_archivo_fuente(archivo)
                archivo_id = resp.get("id") or resp.get("data", {}).get("id")
                log.debug("archivo_persisted", nombre=archivo.nombre, id=archivo_id)

                # Update unidades with the real archivo_id
                for unidad in unidades:
                    if unidad.archivo_id == archivo.id and archivo_id:
                        unidad.archivo_id = archivo_id

                    if archivo_id:
                        try:
                            await aone_client.post_unidad_logica(unidad)
                        except Exception as e:
                            log.warning("unidad_persist_failed", nombre=unidad.nombre, error=str(e))

            except Exception as e:
                log.warning("archivo_persist_failed", nombre=archivo.nombre, error=str(e))

    # ── 6. Collect scores and build escaneo ───────────────────────
    all_scores: list[float] = []
    all_complexities: list[int] = []

    for u in unidades:
        if u.metadata:
            meta = json.loads(u.metadata)
            if meta.get("overall_score"):
                all_scores.append(meta["overall_score"])
        if u.complejidad:
            all_complexities.append(u.complejidad)

    avg_score = round(sum(all_scores) / len(all_scores), 2) if all_scores else 0.0
    max_complexity = max(all_complexities) if all_complexities else 0

    # Count by type
    clases_total = sum(1 for u in unidades if u.tipo == "CLASE")
    funciones_total = sum(1 for u in unidades if u.tipo == "FUNCION")

    # Count by layer
    layer_counts = {"Dominio": 0, "Infraestructura": 0, "Adaptador": 0}
    risk_counts = {"HIGH": 0, "MEDIUM": 0, "LOW": 0}

    for u in unidades:
        if u.metadata:
            meta = json.loads(u.metadata)
            layer = meta.get("capa", "")
            if layer in layer_counts:
                layer_counts[layer] += 1
            risk = meta.get("risk_level", "")
            if risk in risk_counts:
                risk_counts[risk] += 1

    # Determine overall risk
    if avg_score < 50 or max_complexity > 15:
        nivel_riesgo = RiskLevel.HIGH.value
    elif avg_score < 70 or max_complexity >= 10:
        nivel_riesgo = RiskLevel.MEDIUM.value
    else:
        nivel_riesgo = RiskLevel.LOW.value

    escaneo = Escaneo(
        activo_id=activo_id,
        aplicacion_id=aplicacion_id,
        commit_hash=commit_hash,
        escaneado_en=datetime.now(timezone.utc).isoformat(),
        generado_por="code-agent-v2.0",
        score_general=avg_score,
        nivel_riesgo=nivel_riesgo,
        archivos_total=result.processed_files,
        funciones_total=funciones_total,
        clases_total=clases_total,
        metricas=json.dumps({
            "loc_total": project.total_lines,
            "avg_complexity": round(sum(all_complexities) / len(all_complexities), 1) if all_complexities else 0,
            "max_complexity": max_complexity,
            "avg_score": avg_score,
            "languages": project.languages,
        }),
        arquitectura=json.dumps({
            "capas": layer_counts,
            "multi_layer_count": sum(1 for u in unidades
                                     if u.metadata and json.loads(u.metadata).get("compliance", {}).get("has_multi_layer_coupling")),
        }),
        cumplimiento=json.dumps({
            "risk_distribution": risk_counts,
            "loc_ok_pct": round(sum(1 for u in unidades if u.metadata and json.loads(u.metadata).get("compliance", {}).get("loc_ok")) / max(len(unidades), 1) * 100, 1),
            "complexity_ok_pct": round(sum(1 for u in unidades if u.metadata and json.loads(u.metadata).get("compliance", {}).get("complexity_ok")) / max(len(unidades), 1) * 100, 1),
        }),
    )

    # Persist escaneo
    if aone_client:
        try:
            resp = await aone_client.post_escaneo(escaneo)
            result.scan_id = resp.get("id") or resp.get("data", {}).get("id")
            log.info("escaneo_persisted", scan_id=result.scan_id)
        except Exception as e:
            log.warning("escaneo_persist_failed", error=str(e))

    result.score_general = avg_score
    result.nivel_riesgo = nivel_riesgo

    log.info(
        "pipeline_completed",
        version="v2",
        archivos=result.processed_files,
        clases=clases_total,
        funciones=funciones_total,
        score=avg_score,
        riesgo=nivel_riesgo,
        failed=len(result.failed_files),
        context_built=result.project_context is not None,
    )

    return result


def _get_commit_hash(project_path: str) -> str | None:
    """Get git commit hash if available."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=project_path,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            return result.stdout.strip()[:40]
    except Exception:
        pass
    return None
