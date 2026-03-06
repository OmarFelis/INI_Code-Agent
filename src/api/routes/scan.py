"""
Code-Agent — Scan routes.
POST /api/v1/scan — Run a scan and return full results directly.
GET  /api/v1/scan — List recent scan jobs.
GET  /api/v1/scan/{job_id} — Get a stored scan result.
"""

import json
import os
from datetime import datetime, timezone
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.schemas.scan_request import ScanRequest
from src.api.schemas.scan_response import (
    ScanAcceptedResponse,
    ScanResults,
    EscaneoSummary,
    ArchivoFuenteDetail,
    UnidadLogicaDetail,
    ScanJobListItem,
)
from src.db.session import get_session, async_session_factory
from src.db import repository

logger = structlog.get_logger()

router = APIRouter(prefix="/api/v1/scan", tags=["scan"])


def _build_results(result) -> dict:
    """Convert PipelineResult into a serializable dict."""
    archivos = []
    for a in result.archivos:
        archivos.append({
            "nombre": a.nombre,
            "ruta_archivo": a.ruta_archivo,
            "proposito": a.proposito,
            "capa": a.capa,
            "lenguaje": a.lenguaje,
            "total_funciones": a.total_funciones,
            "total_clases": a.total_clases,
            "endpoints": a.endpoints,
            "operaciones_bd": a.operaciones_bd,
            "llamadas_externas": a.llamadas_externas,
            "complejidad_ciclomatica": a.complejidad_ciclomatica,
            "lineas_codigo": a.lineas_codigo,
        })

    unidades = []
    # Track which archivo each unidad belongs to
    archivo_map = {}
    for idx, a in enumerate(result.archivos):
        archivo_map[idx] = a.nombre

    # Build a mapping from activo+archivo index to archivo name
    current_archivo_idx = 0
    current_archivo_unidad_count = 0

    for u in result.unidades:
        meta = json.loads(u.metadata) if u.metadata else {}
        unidades.append({
            "nombre": u.nombre,
            "tipo": u.tipo,
            "archivo": "",  # Will be filled below
            "parent": u.parent_id.replace("TEMP_CLASS_", "") if u.parent_id else None,
            "linea_inicio": u.linea_inicio,
            "linea_fin": u.linea_fin,
            "complejidad": u.complejidad,
            "lineas_codigo": u.lineas_codigo,
            "accede_bd": u.accede_bd,
            "docstring": u.docstring,
            "capa": meta.get("capa"),
            "overall_score": meta.get("overall_score"),
            "risk_level": meta.get("risk_level"),
        })

    # Associate unidades with their archivo
    unidad_idx = 0
    for a_idx, archivo in enumerate(result.archivos):
        count = archivo.total_clases + archivo.total_funciones
        # Handle possible mismatch by counting units with matching archivo
        for i in range(count):
            if unidad_idx < len(unidades):
                unidades[unidad_idx]["archivo"] = archivo.nombre
                unidad_idx += 1

    # Fill remaining
    for i in range(unidad_idx, len(unidades)):
        unidades[i]["archivo"] = "unknown"

    # Aggregated stats
    complexities = [u.complejidad for u in result.unidades if u.complejidad]
    capas = {}
    risk_dist = {"HIGH": 0, "MEDIUM": 0, "LOW": 0}
    for u in result.unidades:
        meta = json.loads(u.metadata) if u.metadata else {}
        capa = meta.get("capa", "Unknown")
        capas[capa] = capas.get(capa, 0) + 1
        risk = meta.get("risk_level", "LOW")
        if risk in risk_dist:
            risk_dist[risk] += 1

    langs = {}
    for a in result.archivos:
        lang = a.lenguaje or "Unknown"
        langs[lang] = langs.get(lang, 0) + 1

    escaneo = {
        "score_general": result.score_general,
        "nivel_riesgo": result.nivel_riesgo,
        "archivos_total": result.processed_files,
        "funciones_total": sum(1 for u in result.unidades if u.tipo == "FUNCION"),
        "clases_total": sum(1 for u in result.unidades if u.tipo == "CLASE"),
        "lineas_total": sum(a.lineas_codigo or 0 for a in result.archivos),
        "commit_hash": result.archivos[0].commit_hash if result.archivos else None,
        "languages": langs,
        "capas": capas,
        "risk_distribution": risk_dist,
        "avg_complexity": round(sum(complexities) / len(complexities), 1) if complexities else 0,
        "max_complexity": max(complexities) if complexities else 0,
    }

    return {
        "escaneo": escaneo,
        "archivos_fuente": archivos,
        "unidades_logicas": unidades,
    }


async def _run_scan_background_task(job_id: UUID, request: ScanRequest):
    """Background task that runs the pipeline and updates the job status."""
    from src.core.analyzers.pipeline import run as run_pipeline
    log = logger.bind(
        job_id=str(job_id),
        microservice=request.microservice_name,
        project_path=request.project_path,
    )

    log.info("background_scan_started")

    async with async_session_factory() as session:
        try:
            # Update status to IN_PROGRESS
            await repository.update_scan_job_status(session, job_id, status="IN_PROGRESS")
            await session.commit()

            # Run pipeline
            result = await run_pipeline(
                project_path=request.project_path,
                activo_id=request.activo_id,
                aplicacion_id=request.aplicacion_id,
                microservice_name=request.microservice_name,
                aone_client=None,
            )

            # Build response
            results_dict = _build_results(result)

            # Update DB to COMPLETED
            await repository.update_scan_job_status(
                session,
                job_id,
                status="COMPLETED",
                total_files=result.total_files,
                processed_files=result.processed_files,
                failed_files=result.failed_files if result.failed_files else None,
                results=results_dict,
            )
            await session.commit()

            log.info(
                "background_scan_completed",
                archivos=result.processed_files,
                clases=results_dict["escaneo"]["clases_total"],
                funciones=results_dict["escaneo"]["funciones_total"],
                score=result.score_general,
                riesgo=result.nivel_riesgo,
            )
            
        except Exception as e:
            log.error("background_scan_failed", error=str(e))
            # Fallback update to FAILED if possible
            try:
                await repository.update_scan_job_status(
                    session,
                    job_id,
                    status="FAILED",
                    failed_files=[{"archivo": "ALL", "error": str(e)}]
                )
                await session.commit()
            except Exception as e_inner:
                log.error("background_scan_failed_to_update_status", error=str(e_inner))


@router.post(
    "",
    response_model=ScanAcceptedResponse,
    status_code=202,
    summary="Queue a code scan",
    description="Queues the specified repository analysis as a background task and returns a job ID.",
)
async def run_scan(
    request: ScanRequest,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
):
    """Queue a code analysis scan."""
    log = logger.bind(
        microservice=request.microservice_name,
        project_path=request.project_path,
    )

    # Validate project_path exists locally
    if not request.repo_url and not os.path.isdir(request.project_path):
        raise HTTPException(
            status_code=400,
            detail=f"project_path does not exist or is not a directory: {request.project_path}",
        )

    # Store initially as QUEUED in DB
    job = await repository.create_scan_job(
        session,
        activo_id=request.activo_id,
        aplicacion_id=request.aplicacion_id,
        microservice_name=request.microservice_name,
        project_path=request.project_path,
        branch=request.branch,
    )
    # The current transaction must commit to make the job ID available for the background task
    await session.commit()
    
    # Add to FastAPI background tasks
    background_tasks.add_task(_run_scan_background_task, job.id, request)
    
    log.info("scan_queued", job_id=str(job.id))

    return ScanAcceptedResponse(
        job_id=str(job.id),
        status="QUEUED"
    )


@router.get(
    "/{job_id}",
    summary="Get a stored scan result",
    description="Returns the stored results of a previously completed scan.",
)
async def get_scan_result(
    job_id: str,
    session: AsyncSession = Depends(get_session),
):
    """Get stored results of a completed scan."""
    try:
        uuid_id = UUID(job_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid job_id format — expected UUID")

    job = await repository.get_scan_job(session, uuid_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Scan job not found: {job_id}")

    return {
        "job_id": str(job.id),
        "status": job.status,
        "microservice_name": job.microservice_name,
        "project_path": job.project_path,
        "total_files": job.total_files,
        "processed_files": job.processed_files,
        "results": job.results,
        "created_at": job.created_at,
    }


@router.get(
    "",
    response_model=list[ScanJobListItem],
    summary="List recent scan jobs",
    description="Returns the most recent scan jobs.",
)
async def list_scans(
    activo_id: str | None = None,
    limit: int = 20,
    session: AsyncSession = Depends(get_session),
):
    """List recent scan jobs."""
    jobs = await repository.list_scan_jobs(session, activo_id=activo_id, limit=limit)
    return [
        ScanJobListItem(
            job_id=str(j.id),
            status=j.status,
            microservice_name=j.microservice_name,
            activo_id=j.activo_id,
            created_at=j.created_at,
        )
        for j in jobs
    ]
