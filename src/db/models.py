"""
Code-Agent — ORM Models for scan_jobs (internal tracking).
"""

import uuid
from datetime import datetime

from sqlalchemy import String, Integer, DateTime, Text, func
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.db.session import Base


class ScanJobORM(Base):
    """Internal table to track scan job status, progress, and full results."""

    __tablename__ = "scan_jobs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    activo_id: Mapped[str] = mapped_column(String(36), nullable=False)
    aplicacion_id: Mapped[str] = mapped_column(String(36), nullable=False)
    microservice_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    project_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    branch: Mapped[str | None] = mapped_column(String(100), nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="QUEUED"
    )  # QUEUED | RUNNING | COMPLETED | PARTIAL | FAILED
    total_files: Mapped[int] = mapped_column(Integer, default=0)
    processed_files: Mapped[int] = mapped_column(Integer, default=0)
    failed_files: Mapped[dict | None] = mapped_column(JSONB, default=list)
    scan_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # --- Full results (stored as JSONB when pipeline completes) ---
    results: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # --- Timestamps ---
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )

    def __repr__(self) -> str:
        return f"<ScanJob {self.id} status={self.status} ms={self.microservice_name}>"
