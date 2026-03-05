"""
Code-Agent — API Response schemas.
"""

from datetime import datetime

from pydantic import BaseModel, Field


class ScanAcceptedResponse(BaseModel):
    """Response when a scan is accepted (202)."""

    job_id: str = Field(description="ID del job de escaneo")
    status: str = Field(default="QUEUED", description="Estado del job")
    message: str = Field(default="Scan job queued successfully")


# ── Detail schemas ────────────────────────────────────────────────

class ArchivoFuenteDetail(BaseModel):
    """Detail of a single analyzed file."""
    nombre: str
    ruta_archivo: str | None = None
    proposito: str | None = None
    capa: str | None = None
    lenguaje: str | None = None
    total_funciones: int = 0
    total_clases: int = 0
    endpoints: int = 0
    operaciones_bd: int = 0
    llamadas_externas: int = 0
    complejidad_ciclomatica: int | None = None
    lineas_codigo: int | None = None


class UnidadLogicaDetail(BaseModel):
    """Detail of a single logical unit (class or function)."""
    nombre: str
    tipo: str                   # CLASE | FUNCION
    archivo: str                # file name this unit belongs to
    parent: str | None = None   # parent class name if method
    linea_inicio: int | None = None
    linea_fin: int | None = None
    complejidad: int | None = None
    lineas_codigo: int | None = None
    accede_bd: bool = False
    docstring: bool = False
    capa: str | None = None
    overall_score: float | None = None
    risk_level: str | None = None


class EscaneoSummary(BaseModel):
    """Scan-level summary with aggregated metrics."""
    score_general: float | None = None
    nivel_riesgo: str | None = None
    archivos_total: int = 0
    funciones_total: int = 0
    clases_total: int = 0
    lineas_total: int = 0
    commit_hash: str | None = None
    languages: dict[str, int] = Field(default_factory=dict)
    capas: dict[str, int] = Field(default_factory=dict)
    risk_distribution: dict[str, int] = Field(default_factory=dict)
    avg_complexity: float = 0
    max_complexity: int = 0


class ScanResults(BaseModel):
    """Full results of a completed scan."""
    escaneo: EscaneoSummary
    archivos_fuente: list[ArchivoFuenteDetail] = []
    unidades_logicas: list[UnidadLogicaDetail] = []


# ── Main response ────────────────────────────────────────────────

class ScanStatusResponse(BaseModel):
    """Response for GET /api/v1/scan/{job_id}."""

    job_id: str
    status: str  # QUEUED | RUNNING | COMPLETED | PARTIAL | FAILED
    microservice_name: str | None = None
    project_path: str | None = None
    branch: str | None = None
    activo_id: str
    aplicacion_id: str

    # --- Progress ---
    total_files: int = 0
    processed_files: int = 0
    failed_files: list | None = None

    # --- Results (when COMPLETED) ---
    results: ScanResults | None = None
    error_message: str | None = None

    # --- Timestamps ---
    created_at: datetime | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None


class ScanJobListItem(BaseModel):
    """Summary item for listing scan jobs."""

    job_id: str
    status: str
    microservice_name: str | None = None
    activo_id: str
    created_at: datetime | None = None


class HealthResponse(BaseModel):
    """Response for GET /health."""

    status: str = "healthy"
    service: str = "code-agent"
    version: str
    database: str = "unknown"  # connected | disconnected
