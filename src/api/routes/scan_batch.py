"""
Code-Agent — Batch scan routes.
POST /api/v1/scan/batch      — Queue multiple scans at once, each as an independent job.
DELETE /api/v1/scan/{job_id}/cleanup — Cleanup cached repo for a scan job.
"""

import os
import shutil
from urllib.parse import urlparse
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.schemas.scan_request import BatchScanRequest
from src.db.session import get_session
from src.db import repository
from src.config import settings

logger = structlog.get_logger()

from src.api.dependencies.auth import verify_api_token

router = APIRouter(
    prefix="/api/v1/scan",
    tags=["scan-batch"],
    dependencies=[Depends(verify_api_token)],
)


@router.post(
    "/batch",
    status_code=202,
    summary="Queue multiple code scans",
    description="Queues N repository scans as independent jobs. Each scan runs in parallel and returns its own job_id.",
)
async def batch_scan(
    request: BatchScanRequest,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
):
    """Queue multiple scans as independent jobs."""
    from src.api.routes.scan import _run_scan_background_task

    # ── Validate all requests before creating any job ─────────────
    allowed_domains = [d.strip() for d in settings.allowed_git_domains.split(",")]

    for idx, scan_req in enumerate(request.scans):
        label = f"Scan #{idx + 1} ({scan_req.microservice_name})"

        if scan_req.repo_url:
            parsed_url = urlparse(scan_req.repo_url)
            domain = parsed_url.netloc.split(":")[0]
            if not any(domain.endswith(d) for d in allowed_domains):
                raise HTTPException(
                    status_code=403,
                    detail=f"{label}: domain '{domain}' is not in the allowed list: {settings.allowed_git_domains}",
                )
        else:
            if not os.path.isdir(scan_req.project_path):
                raise HTTPException(
                    status_code=400,
                    detail=f"{label}: project_path does not exist or is not a directory: {scan_req.project_path}",
                )

    # ── Create and enqueue each job independently ─────────────────
    jobs = []

    for scan_req in request.scans:
        job = await repository.create_scan_job(
            session,
            activo_id=scan_req.activo_id,
            aplicacion_id=scan_req.aplicacion_id,
            microservice_name=scan_req.microservice_name,
            project_path=scan_req.project_path,
            branch=scan_req.branch,
        )
        jobs.append((job.id, scan_req))

    await session.commit()

    for job_id, scan_req in jobs:
        background_tasks.add_task(_run_scan_background_task, job_id, scan_req)

    logger.info("batch_scan_queued", total=len(jobs))

    return [
        {
            "job_id": str(job_id),
            "microservice_name": scan_req.microservice_name,
            "status": "QUEUED",
            "message": "Scan job queued successfully",
        }
        for job_id, scan_req in jobs
    ]


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
