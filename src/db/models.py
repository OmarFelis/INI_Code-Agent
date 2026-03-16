"""
Code-Agent — ORM Models for infra schema.
"""

import uuid
from datetime import datetime

from sqlalchemy import String, Integer, DateTime, Text, func, JSON, Uuid, Boolean, Numeric, ForeignKey
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


class ArchivoFuenteORM(Base):
    """One row per source file analyzed in a scan."""

    __tablename__ = "archivos_fuente"
    __table_args__ = {"schema": "infra"}

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    escaneo_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("infra.escaneos.id"), nullable=False)
    activo_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    aplicacion_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    nombre: Mapped[str] = mapped_column(String(255), nullable=False)
    ruta_archivo: Mapped[str | None] = mapped_column(Text, nullable=True)
    proposito: Mapped[str | None] = mapped_column(String(100), nullable=True)
    capa: Mapped[str | None] = mapped_column(String(100), nullable=True)
    lenguaje: Mapped[str | None] = mapped_column(String(50), nullable=True)
    total_funciones: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_clases: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    endpoints: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    operaciones_bd: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    llamadas_externas: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    complejidad_ciclomatica: Mapped[int | None] = mapped_column(Integer, nullable=True)
    lineas_codigo: Mapped[int | None] = mapped_column(Integer, nullable=True)
    resumen: Mapped[str | None] = mapped_column(Text, nullable=True)
    meta: Mapped[dict | None] = mapped_column("metadata", JSON, nullable=True)
    commit_hash: Mapped[str | None] = mapped_column(String(100), nullable=True)
    build_number: Mapped[str | None] = mapped_column(String(100), nullable=True)
    escaneado_en: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    activo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    analisis_ia: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    escaneado: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    def __repr__(self) -> str:
        return f"<ArchivoFuente {self.nombre} escaneo={self.escaneo_id}>"


class UnidadLogicaORM(Base):
    """One row per logical unit (function or class) analyzed in a scan."""

    __tablename__ = "unidades_logicas"
    __table_args__ = {"schema": "infra"}

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    escaneo_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("infra.escaneos.id"), nullable=False)
    activo_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("infra.unidades_logicas.id"), nullable=True)
    archivo_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("infra.archivos_fuente.id"), nullable=True)
    aplicacion_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    nombre: Mapped[str] = mapped_column(String(255), nullable=False)
    tipo: Mapped[str] = mapped_column(String(20), nullable=False)  # FUNCION | CLASE
    linea_inicio: Mapped[int | None] = mapped_column(Integer, nullable=True)
    linea_fin: Mapped[int | None] = mapped_column(Integer, nullable=True)
    complejidad: Mapped[int | None] = mapped_column(Integer, nullable=True)
    lineas_codigo: Mapped[int | None] = mapped_column(Integer, nullable=True)
    accede_bd: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    llamadas_externas: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    docstring: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    overall_score: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    risk_level: Mapped[str | None] = mapped_column(String(20), nullable=True)
    resumen: Mapped[str | None] = mapped_column(Text, nullable=True)
    modifica_estado: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    auto_clasificado: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    meta: Mapped[dict | None] = mapped_column("metadata", JSON, nullable=True)
    activo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    escaneado: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    analisis_ia: Mapped[dict | None] = mapped_column(JSON, nullable=True)

class ReglaNegocioORM(Base):
    """One row per business rule extracted by AI from a logical unit."""

    __tablename__ = "reglas_negocio"
    __table_args__ = {"schema": "producto"}

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    unidad_logica_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("infra.unidades_logicas.id"), nullable=False)
    activo_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    aplicacion_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    descripcion: Mapped[str] = mapped_column(Text, nullable=False)
    codigo_relacionado: Mapped[str | None] = mapped_column(Text, nullable=True)
    creado_por_ia: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    activo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    def __repr__(self) -> str:
        return f"<ReglaNegocio {self.id} unidad={self.unidad_logica_id}>"
