"""
Code-Agent — Pydantic domain models.
These represent the data structures used throughout the pipeline.
They map to A-ONE's infra_detalle tables but are NOT ORM models.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


# ============================================
# Enums
# ============================================

class LanguageType(str, Enum):
    PYTHON = "Python"
    JAVA = "Java"
    JAVASCRIPT = "JavaScript"
    TYPESCRIPT = "TypeScript"


class ArchitectureLayer(str, Enum):
    DOMINIO = "Dominio"
    INFRAESTRUCTURA = "Infraestructura"
    ADAPTADOR = "Adaptador"


class RiskLevel(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class UnitType(str, Enum):
    CLASE = "CLASE"
    FUNCION = "FUNCION"
    INTERFAZ = "INTERFAZ"
    ENUM = "ENUM"


class ScanStatus(str, Enum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"


# ============================================
# A-ONE Models (infra_detalle.*)
# ============================================

class ArchivoFuente(BaseModel):
    """Maps to infra_detalle.archivos_fuente"""

    id: str | None = None
    activo_id: str
    aplicacion_id: str
    nombre: str
    ruta_archivo: str | None = None
    proposito: str | None = None  # VARCHAR(30): Controller, Service, Repository, etc.
    capa: str | None = None       # VARCHAR(20): Dominio, Infraestructura, Adaptador
    lenguaje: str | None = None   # VARCHAR(20): Java, Python, JavaScript, TypeScript
    total_funciones: int = 0
    total_clases: int = 0
    endpoints: int = 0            # INTEGER — count, not array
    operaciones_bd: int = 0       # INTEGER — count, not array
    llamadas_externas: int = 0    # INTEGER — count, not array
    complejidad_ciclomatica: int | None = None
    lineas_codigo: int | None = None
    resumen: str | None = None    # LLM-generated (Phase 2)
    metadata: str | None = None   # TEXT — JSON string with extra detail
    build_number: str | None = None
    commit_hash: str | None = None
    escaneado_en: str | None = None
    activo: bool = True


class UnidadLogica(BaseModel):
    """Maps to infra_detalle.unidades_logicas"""

    id: str | None = None
    archivo_id: str
    parent_id: str | None = None
    activo_id: str
    aplicacion_id: str
    nombre: str
    tipo: str                     # CLASE | FUNCION | INTERFAZ | ENUM
    linea_inicio: int | None = None
    linea_fin: int | None = None
    complejidad: int | None = None
    lineas_codigo: int | None = None
    accede_bd: bool = False
    llamadas_externas: int = 0    # INTEGER — count
    docstring: bool = False
    resumen: str | None = None    # LLM-generated (Phase 2)
    metadata: str | None = None   # TEXT — JSON string with scoring, capa, risk, etc.
    activo: bool = True


class Escaneo(BaseModel):
    """Maps to infra_detalle.escaneos"""

    id: str | None = None
    activo_id: str
    aplicacion_id: str
    build_number: str | None = None
    commit_hash: str | None = None
    escaneado_en: str | None = None
    generado_por: str = "code-agent-v1.0"
    score_general: float | None = None
    nivel_riesgo: str = RiskLevel.LOW
    archivos_total: int = 0
    funciones_total: int = 0
    clases_total: int = 0
    dominios_negocio: str | None = None  # TEXT — JSON string
    metricas: str | None = None          # TEXT — JSON string
    arquitectura: str | None = None      # TEXT — JSON string
    seguridad: str | None = None         # TEXT — JSON string
    rendimiento: str | None = None       # TEXT — JSON string
    negocio: str | None = None           # TEXT — JSON string
    cumplimiento: str | None = None      # TEXT — JSON string


# ============================================
# Pipeline Models (internal)
# ============================================

class FileAnalysis(BaseModel):
    """Output from language-specific analyzers."""

    file_path: str
    file_name: str
    language: LanguageType
    total_lines: int = 0
    classes: list[str] = Field(default_factory=list)
    functions: list[str] = Field(default_factory=list)
    imports: list[str] = Field(default_factory=list)
    api_endpoints: list[dict] = Field(default_factory=list)
    database_calls: list[dict] = Field(default_factory=list)
    external_calls: list[dict] = Field(default_factory=list)
    complexity: int = 0
    decorators: list[str] = Field(default_factory=list)


class ProjectAnalysis(BaseModel):
    """Aggregated analysis of all files in a project."""

    project_name: str
    project_path: str
    files: list[FileAnalysis] = Field(default_factory=list)
    total_files: int = 0
    total_lines: int = 0
    languages: dict[str, int] = Field(default_factory=dict)


class BusinessRule(BaseModel):
    """Business rule extracted by LLM."""

    texto: str
    funcion: str
    archivo: str
    confianza: float = 0.0


class UnitMetadata(BaseModel):
    """Structure for unidades_logicas.metadata JSON content."""

    capa: str | None = None
    proposito: str | None = None
    overall_score: float | None = None
    risk_level: str | None = None
    compliance: dict | None = None
    imports: list[str] = Field(default_factory=list)
    decorators: list[str] = Field(default_factory=list)
    parameters: list[str] = Field(default_factory=list)
    return_type: str | None = None
    reglas_negocio: list[str] = Field(default_factory=list)


# ============================================
# Context Models (Pipeline V2)
# ============================================

class FileContext(BaseModel):
    """Context information for a single file, built from the dependency graph."""

    file_path: str
    file_name: str
    module: str = ""                                      # Package/directory grouping
    layer: str | None = None                              # Dominio, Infraestructura, Adaptador
    imports_from: list[str] = Field(default_factory=list)  # Files this file depends on
    imported_by: list[str] = Field(default_factory=list)   # Files that depend on this file
    sibling_files: list[str] = Field(default_factory=list) # Other files in the same module
    module_purpose: str = ""                               # Inferred purpose of the module


class ProjectManifest(BaseModel):
    """High-level architecture summary of the entire project."""

    project_name: str
    total_files: int = 0
    total_lines: int = 0
    layers: dict[str, int] = Field(default_factory=dict)       # {"Dominio": 45, ...}
    languages: dict[str, int] = Field(default_factory=dict)    # {"Java": 65, ...}
    modules: list[str] = Field(default_factory=list)            # ["cards", "auth", ...]


class ProjectContext(BaseModel):
    """Full project context built by the ContextBuilder after Pass 1."""

    manifest: ProjectManifest
    file_contexts: dict[str, FileContext] = Field(default_factory=dict)  # keyed by file_path
