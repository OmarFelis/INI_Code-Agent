"""
Code-Agent — Data access layer for scan_jobs.
"""

import uuid
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import ScanJobORM


async def create_scan_job(
    session: AsyncSession,
    *,
    activo_id: str,
    aplicacion_id: str,
    microservice_name: str | None = None,
    project_path: str | None = None,
    branch: str | None = None,
    batch_id: str | None = None,
) -> ScanJobORM:
    """Create a new scan job with status QUEUED."""
    job = ScanJobORM(
        activo_id=activo_id,
        aplicacion_id=aplicacion_id,
        microservice_name=microservice_name,
        project_path=project_path,
        branch=branch,
        batch_id=batch_id,
        status="QUEUED",
    )
    session.add(job)
    await session.flush()
    return job


async def get_scan_job(session: AsyncSession, job_id: uuid.UUID) -> ScanJobORM | None:
    """Get a scan job by ID."""
    result = await session.execute(
        select(ScanJobORM).where(ScanJobORM.id == job_id)
    )
    return result.scalar_one_or_none()


async def update_scan_job_status(
    session: AsyncSession,
    job_id: uuid.UUID,
    *,
    status: str,
    total_files: int | None = None,
    processed_files: int | None = None,
    failed_files: list | None = None,
    scan_id: str | None = None,
    error_message: str | None = None,
    results: dict | None = None,
    project_path: str | None = None,
) -> None:
    """Update scan job status and progress fields."""
    values: dict = {"status": status}

    if status == "RUNNING":
        values["started_at"] = datetime.utcnow()
    elif status in ("COMPLETED", "PARTIAL", "FAILED"):
        values["completed_at"] = datetime.utcnow()

    if total_files is not None:
        values["total_files"] = total_files
    if processed_files is not None:
        values["processed_files"] = processed_files
    if failed_files is not None:
        values["failed_files"] = failed_files
    if scan_id is not None:
        values["scan_id"] = scan_id
    if error_message is not None:
        values["error_message"] = error_message
    if results is not None:
        values["results"] = results
    if project_path is not None:
        values["project_path"] = project_path

    await session.execute(
        update(ScanJobORM).where(ScanJobORM.id == job_id).values(**values)
    )


async def list_scan_jobs(
    session: AsyncSession,
    *,
    activo_id: str | None = None,
    limit: int = 20,
) -> list[ScanJobORM]:
    """List scan jobs, optionally filtered by activo_id."""
    query = select(ScanJobORM).order_by(ScanJobORM.created_at.desc()).limit(limit)
    if activo_id:
        query = query.where(ScanJobORM.activo_id == activo_id)
    result = await session.execute(query)
    return list(result.scalars().all())


async def list_batch_jobs(
    session: AsyncSession,
    batch_id: str,
) -> list[ScanJobORM]:
    """List all scan jobs belonging to a batch."""
    result = await session.execute(
        select(ScanJobORM)
        .where(ScanJobORM.batch_id == batch_id)
        .order_by(ScanJobORM.created_at.asc())
    )
    return list(result.scalars().all())

