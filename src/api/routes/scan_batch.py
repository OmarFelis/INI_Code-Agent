"""
Code-Agent — Batch scan routes.
POST /api/v1/scan/batch  — Queue multiple scans at once.
GET  /api/v1/scan/batch/{batch_id} — Get consolidated batch status.
DELETE /api/v1/scan/{job_id}/cleanup — Cleanup cached repo for a scan job.
"""

import os
import shutil
import uuid as uuid_mod
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.schemas.scan_request import BatchScanRequest
from src.db.session import get_session, async_session_factory
from src.db import repository
from src.config import settings

logger = structlog.get_logger()

from src.api.dependencies.auth import verify_api_token

router = APIRouter(
    prefix="/api/v1/scan",
    tags=["scan-batch"],
    dependencies=[Depends(verify_api_token)],
)


# ── Batch Scan ────────────────────────────────────────────────────


@router.post(
    "/batch",
    status_code=202,
    summary="Queue multiple code scans",
    description="Queues N repository scans as a single batch. Each scan runs sequentially.",
)
async def batch_scan(
    request: BatchScanRequest,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
):
    """Queue multiple scans as a batch."""
    batch_id = str(uuid_mod.uuid4())
    log = logger.bind(batch_id=batch_id, total=len(request.scans))

    jobs = []
    for scan_req in request.scans:
        job = await repository.create_scan_job(
            session,
            activo_id=scan_req.activo_id,
            aplicacion_id=scan_req.aplicacion_id,
            microservice_name=scan_req.microservice_name,
            project_path=scan_req.project_path,
            branch=scan_req.branch,
            batch_id=batch_id,
        )
        jobs.append({
            "job_id": str(job.id),
            "microservice_name": scan_req.microservice_name,
            "status": "QUEUED",
        })

    await session.commit()

    # Run batch in background (sequential to avoid overloading Bedrock)
    background_tasks.add_task(
        _run_batch_background_task, batch_id, request.scans
    )

    log.info("batch_scan_queued", jobs=len(jobs))

    return {
        "batch_id": batch_id,
        "total_scans": len(request.scans),
        "jobs": jobs,
    }


async def _run_batch_background_task(batch_id: str, scans: list):
    """Background task: run scans sequentially within a batch."""
    from src.api.routes.scan import _run_scan_background_task

    log = logger.bind(batch_id=batch_id, total=len(scans))
    log.info("batch_background_started")

    async with async_session_factory() as session:
        batch_jobs = await repository.list_batch_jobs(session, batch_id)

    for idx, (scan_req, job_orm) in enumerate(zip(scans, batch_jobs)):
        log.info("batch_running_scan", index=idx + 1, ms=scan_req.microservice_name)
        try:
            await _run_scan_background_task(job_orm.id, scan_req)
        except Exception as e:
            log.error("batch_scan_failed", ms=scan_req.microservice_name, error=str(e))

    log.info("batch_background_completed")


# ── Batch Status ──────────────────────────────────────────────────


@router.get(
    "/batch/{batch_id}",
    summary="Get batch scan status",
    description="Returns consolidated status of all scans in a batch.",
)
async def get_batch_status(
    batch_id: str,
    session: AsyncSession = Depends(get_session),
):
    """Get consolidated status of a batch."""
    jobs = await repository.list_batch_jobs(session, batch_id)
    if not jobs:
        raise HTTPException(status_code=404, detail=f"Batch not found: {batch_id}")

    statuses = [j.status for j in jobs]
    completed = sum(1 for s in statuses if s == "COMPLETED")
    failed = sum(1 for s in statuses if s == "FAILED")

    if all(s == "COMPLETED" for s in statuses):
        overall = "COMPLETED"
    elif any(s in ("IN_PROGRESS", "QUEUED") for s in statuses):
        overall = "IN_PROGRESS"
    elif failed == len(statuses):
        overall = "FAILED"
    else:
        overall = "PARTIAL"

    return {
        "batch_id": batch_id,
        "status": overall,
        "completed": completed,
        "failed": failed,
        "total": len(jobs),
        "jobs": [
            {
                "job_id": str(j.id),
                "microservice_name": j.microservice_name,
                "status": j.status,
                "score": (j.results or {}).get("escaneo", {}).get("score_general"),
                "total_files": j.total_files,
            }
            for j in jobs
        ],
    }


# ── Cleanup ───────────────────────────────────────────────────────


@router.delete(
    "/{job_id}/cleanup",
    summary="Cleanup cached repository",
    description="Deletes the cached repository for a completed scan job to free disk space.",
)
async def cleanup_job_repo(
    job_id: str,
    session: AsyncSession = Depends(get_session),
):
    """Delete cached repo for a scan job."""
    try:
        uuid_id = UUID(job_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid job_id format — expected UUID")

    job = await repository.get_scan_job(session, uuid_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Scan job not found: {job_id}")

    cache_path = os.path.abspath(f"{settings.repos_cache_dir}/{job_id}")
    if os.path.exists(cache_path):
        shutil.rmtree(cache_path, ignore_errors=True)
        return {"message": f"Cache cleaned for job {job_id}", "path": cache_path}
    else:
        return {"message": f"No cached repo found for job {job_id}"}
