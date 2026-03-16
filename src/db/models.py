"""
Code-Agent — ORM Models for infra.escaneos.
"""

import uuid
from datetime import datetime

from sqlalchemy import String, Integer, DateTime, Text, func, JSON, Uuid, Boolean, Numeric
from sqlalchemy.orm import Mapped, mapped_column

from src.db.session import Base


class EscaneoORM(Base):
    """Internal table to track scan job status, progress, and full results."""

    __tablename__ = "escaneos"
    __table_args__ = {"schema": "infra"}

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    activo_id: Mapped[str] = mapped_column(String(36), nullable=False)
    aplicacion_id: Mapped[str] = mapped_column(String(36), nullable=False)
    microservice_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    project_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    branch: Mapped[str | None] = mapped_column(String(100), nullable=True)
    repo_url: Mapped[str | None] = mapped_column(String, nullable=True)
    commit_hash: Mapped[str | None] = mapped_column(String, nullable=True)
    build_number: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="QUEUED"
    )  # QUEUED | RUNNING | COMPLETED | PARTIAL | FAILED
    generado_por: Mapped[str | None] = mapped_column(String, nullable=True)
    score_general: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    nivel_riesgo: Mapped[str | None] = mapped_column(String, nullable=True)
    archivos_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    funciones_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    clases_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    lineas_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    metricas: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    arquitectura: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    seguridad: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    negocio: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    dominios_negocio: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    cumplimiento: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    rendimiento: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    total_files: Mapped[int] = mapped_column(Integer, default=0)
    processed_files: Mapped[int] = mapped_column(Integer, default=0)
    total_files_processed: Mapped[int | None] = mapped_column(Integer, nullable=True)
    failed_files: Mapped[dict | None] = mapped_column(JSON, default=list)
    scan_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    batch_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    results: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    activo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # --- Timestamps ---
    escaneado_en: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    def __repr__(self) -> str:
        return f"<Escaneo {self.id} status={self.status} ms={self.microservice_name}>"
