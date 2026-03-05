"""
Code-Agent — Pipeline Orchestrator.
Coordinates the full scan flow:
  1. Analyze project files
  2. Extract logical units with scoring
  3. Persist to A-ONE via HTTP
  4. Create scan summary (escaneo)
"""

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import structlog

from src.core.analyzers.project_analyzer import ProjectAnalyzerService
from src.core.analyzers import logical_unit_extractor
from src.integrations.aone_client import AOneClient
from src.models.domain import (
    ArchivoFuente,
    UnidadLogica,
    Escaneo,
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


async def run(
    project_path: str,
    activo_id: str,
    aplicacion_id: str,
    microservice_name: str,
    aone_client: AOneClient | None = None,
    on_file_processed: callable = None,
) -> PipelineResult:
    """
    Execute the full scan pipeline.

    Args:
        project_path: Local path to the repository.
        activo_id: UUID of the asset in infra.activos.
        aplicacion_id: UUID of the app in producto.aplicaciones.
        microservice_name: Human-readable name.
        aone_client: Optional A-ONE HTTP client for persistence.
        on_file_processed: Optional callback(processed, total, file_name) for progress.

    Returns:
        PipelineResult with all extracted data.
    """
    log = logger.bind(microservice=microservice_name, path=project_path)
    result = PipelineResult()

    # ── 1. Analyze project ────────────────────────────────────
    log.info("pipeline_phase1_analyze_start")
    analyzer_service = ProjectAnalyzerService()
    project = analyzer_service.analyze_project(project_path, microservice_name)
    result.total_files = project.total_files

    log.info("pipeline_phase1_analyze_done", files=project.total_files, lines=project.total_lines)

    # ── 2. Get commit hash ────────────────────────────────────
    commit_hash = _get_commit_hash(project_path)

    # ── 3. Process each file ──────────────────────────────────
    all_scores: list[float] = []
    all_complexities: list[int] = []

    for idx, file_analysis in enumerate(project.files):
        file_abs_path = str(Path(project_path) / file_analysis.file_path)
        try:
            # Extract hierarchy
            archivo, unidades = logical_unit_extractor.extract(
                file_analysis=file_analysis,
                file_path_absolute=file_abs_path,
                activo_id=activo_id,
                aplicacion_id=aplicacion_id,
            )

            # Set commit hash and timestamp
            archivo.commit_hash = commit_hash
            archivo.escaneado_en = datetime.now(timezone.utc).isoformat()

            # Persist archivo_fuente to A-ONE
            archivo_id = None
            if aone_client:
                try:
                    resp = await aone_client.post_archivo_fuente(archivo)
                    archivo_id = resp.get("id") or resp.get("data", {}).get("id")
                    log.debug("archivo_persisted", nombre=archivo.nombre, id=archivo_id)
                except Exception as e:
                    log.warning("archivo_persist_failed", nombre=archivo.nombre, error=str(e))

            # Set archivo_id on all unidades and persist
            for unidad in unidades:
                if archivo_id:
                    unidad.archivo_id = archivo_id

                if aone_client and archivo_id:
                    try:
                        # Replace temp parent_ids with real IDs
                        # (For now, parent_id is a temp placeholder — will be resolved below)
                        await aone_client.post_unidad_logica(unidad)
                    except Exception as e:
                        log.warning("unidad_persist_failed", nombre=unidad.nombre, error=str(e))

            # Collect scores
            for u in unidades:
                if u.metadata:
                    meta = json.loads(u.metadata)
                    if meta.get("overall_score"):
                        all_scores.append(meta["overall_score"])
                if u.complejidad:
                    all_complexities.append(u.complejidad)

            result.archivos.append(archivo)
            result.unidades.extend(unidades)
            result.processed_files += 1

            # Progress callback
            if on_file_processed:
                on_file_processed(result.processed_files, result.total_files, archivo.nombre)

        except Exception as e:
            log.error("file_processing_failed", file=file_analysis.file_name, error=str(e))
            result.failed_files.append({
                "archivo": file_analysis.file_name,
                "error": str(e),
            })

    # ── 4. Build and persist escaneo ──────────────────────────
    avg_score = round(sum(all_scores) / len(all_scores), 2) if all_scores else 0.0
    max_complexity = max(all_complexities) if all_complexities else 0

    # Count by type
    clases_total = sum(1 for u in result.unidades if u.tipo == "CLASE")
    funciones_total = sum(1 for u in result.unidades if u.tipo == "FUNCION")

    # Count by layer
    layer_counts = {"Dominio": 0, "Infraestructura": 0, "Adaptador": 0}
    risk_counts = {"HIGH": 0, "MEDIUM": 0, "LOW": 0}

    for u in result.unidades:
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
        generado_por="code-agent-v1.0",
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
            "multi_layer_count": sum(1 for u in result.unidades
                                     if u.metadata and json.loads(u.metadata).get("compliance", {}).get("has_multi_layer_coupling")),
        }),
        cumplimiento=json.dumps({
            "risk_distribution": risk_counts,
            "loc_ok_pct": round(sum(1 for u in result.unidades if u.metadata and json.loads(u.metadata).get("compliance", {}).get("loc_ok")) / max(len(result.unidades), 1) * 100, 1),
            "complexity_ok_pct": round(sum(1 for u in result.unidades if u.metadata and json.loads(u.metadata).get("compliance", {}).get("complexity_ok")) / max(len(result.unidades), 1) * 100, 1),
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
        archivos=result.processed_files,
        clases=clases_total,
        funciones=funciones_total,
        score=avg_score,
        riesgo=nivel_riesgo,
        failed=len(result.failed_files),
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
