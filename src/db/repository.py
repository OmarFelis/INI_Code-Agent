"""
Code-Agent — Data access layer.
"""

import uuid
from datetime import datetime, timezone


def _utcnow() -> datetime:
    """Return current UTC time as naive datetime (TIMESTAMP WITHOUT TIME ZONE)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import EscaneoORM, ArchivoFuenteORM, UnidadLogicaORM, ReglaNegocioORM


async def find_completed_scan_by_commit(
    session: AsyncSession,
    activo_id: str,
    microservice_name: str,
    commit_hash: str,
) -> EscaneoORM | None:
    """Find an existing COMPLETED scan for the same activo+microservice+commit."""
    result = await session.execute(
        select(EscaneoORM).where(
            EscaneoORM.activo_id == activo_id,
            EscaneoORM.microservice_name == microservice_name,
            EscaneoORM.commit_hash == commit_hash,
            EscaneoORM.status == "COMPLETED",
        ).limit(1)
    )
    return result.scalar_one_or_none()


async def create_scan_job(
    session: AsyncSession,
    *,
    activo_id: str,
    aplicacion_id: str,
    microservice_name: str | None = None,
    project_path: str | None = None,
    branch: str | None = None,
    batch_id: str | None = None,
) -> EscaneoORM:
    """Create a new escaneo with status QUEUED."""
    job = EscaneoORM(
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


async def get_scan_job(session: AsyncSession, job_id: uuid.UUID) -> EscaneoORM | None:
    """Get an escaneo by ID."""
    result = await session.execute(
        select(EscaneoORM).where(EscaneoORM.id == job_id)
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
    commit_hash: str | None = None,
) -> None:
    """Update scan job status and progress fields."""
    values: dict = {"status": status}

    if status == "RUNNING":
        values["started_at"] = _utcnow()
    elif status in ("COMPLETED", "PARTIAL", "FAILED"):
        values["completed_at"] = _utcnow()

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
    if commit_hash is not None:
        values["commit_hash"] = commit_hash

    await session.execute(
        update(EscaneoORM).where(EscaneoORM.id == job_id).values(**values)
    )


async def list_scan_jobs(
    session: AsyncSession,
    *,
    activo_id: str | None = None,
    limit: int = 20,
) -> list[EscaneoORM]:
    """List escaneos, optionally filtered by activo_id."""
    query = select(EscaneoORM).order_by(EscaneoORM.created_at.desc()).limit(limit)
    if activo_id:
        query = query.where(EscaneoORM.activo_id == activo_id)
    result = await session.execute(query)
    return list(result.scalars().all())


async def list_batch_jobs(
    session: AsyncSession,
    batch_id: str,
) -> list[EscaneoORM]:
    """List all escaneos belonging to a batch."""
    result = await session.execute(
        select(EscaneoORM)
        .where(EscaneoORM.batch_id == batch_id)
        .order_by(EscaneoORM.created_at.asc())
    )
    return list(result.scalars().all())


# ── archivos_fuente ───────────────────────────────────────────────

async def create_archivo_fuente(
    session: AsyncSession,
    *,
    escaneo_id: uuid.UUID,
    activo_id: str,
    aplicacion_id: str,
    nombre: str,
    ruta_archivo: str | None = None,
    proposito: str | None = None,
    capa: str | None = None,
    lenguaje: str | None = None,
    total_funciones: int = 0,
    total_clases: int = 0,
    endpoints: int = 0,
    operaciones_bd: int = 0,
    llamadas_externas: int = 0,
    complejidad_ciclomatica: int | None = None,
    lineas_codigo: int | None = None,
    metadata: dict | None = None,
    commit_hash: str | None = None,
    build_number: str | None = None,
    escaneado_en: datetime | None = None,
) -> ArchivoFuenteORM:
    archivo = ArchivoFuenteORM(
        escaneo_id=escaneo_id,
        activo_id=uuid.UUID(activo_id) if isinstance(activo_id, str) else activo_id,
        aplicacion_id=uuid.UUID(aplicacion_id) if isinstance(aplicacion_id, str) else aplicacion_id,
        nombre=nombre,
        ruta_archivo=ruta_archivo,
        proposito=proposito,
        capa=capa,
        lenguaje=lenguaje,
        total_funciones=total_funciones,
        total_clases=total_clases,
        endpoints=endpoints,
        operaciones_bd=operaciones_bd,
        llamadas_externas=llamadas_externas,
        complejidad_ciclomatica=complejidad_ciclomatica,
        lineas_codigo=lineas_codigo,
        meta=metadata,
        commit_hash=commit_hash,
        build_number=build_number,
        escaneado_en=escaneado_en,
    )
    session.add(archivo)
    await session.flush()
    return archivo


async def update_archivo_analisis_ia(
    session: AsyncSession,
    archivo_id: uuid.UUID,
    analisis_ia: dict | None,
) -> None:
    await session.execute(
        update(ArchivoFuenteORM)
        .where(ArchivoFuenteORM.id == archivo_id)
        .values(analisis_ia=analisis_ia, updated_at=_utcnow())
    )


async def get_archivos_by_escaneo(
    session: AsyncSession,
    escaneo_id: uuid.UUID,
) -> list[ArchivoFuenteORM]:
    result = await session.execute(
        select(ArchivoFuenteORM).where(ArchivoFuenteORM.escaneo_id == escaneo_id)
    )
    return list(result.scalars().all())


# ── unidades_logicas ──────────────────────────────────────────────

async def create_unidad_logica(
    session: AsyncSession,
    *,
    escaneo_id: uuid.UUID,
    activo_id: str,
    aplicacion_id: str,
    archivo_id: uuid.UUID | None = None,
    parent_id: uuid.UUID | None = None,
    nombre: str,
    tipo: str,
    linea_inicio: int | None = None,
    linea_fin: int | None = None,
    complejidad: int | None = None,
    lineas_codigo: int | None = None,
    accede_bd: bool = False,
    llamadas_externas: int = 0,
    docstring: bool = False,
    overall_score: float | None = None,
    risk_level: str | None = None,
    metadata: dict | None = None,
) -> UnidadLogicaORM:
    unidad = UnidadLogicaORM(
        escaneo_id=escaneo_id,
        activo_id=uuid.UUID(activo_id) if isinstance(activo_id, str) else activo_id,
        aplicacion_id=uuid.UUID(aplicacion_id) if isinstance(aplicacion_id, str) else aplicacion_id,
        archivo_id=archivo_id,
        parent_id=parent_id,
        nombre=nombre,
        tipo=tipo,
        linea_inicio=linea_inicio,
        linea_fin=linea_fin,
        complejidad=complejidad,
        lineas_codigo=lineas_codigo,
        accede_bd=accede_bd,
        llamadas_externas=llamadas_externas,
        docstring=docstring,
        overall_score=overall_score,
        risk_level=risk_level,
        meta=metadata,
    )
    session.add(unidad)
    await session.flush()
    return unidad


async def update_unidad_analisis_ia(
    session: AsyncSession,
    unidad_id: uuid.UUID,
    analisis_ia: dict | None,
) -> None:
    await session.execute(
        update(UnidadLogicaORM)
        .where(UnidadLogicaORM.id == unidad_id)
        .values(analisis_ia=analisis_ia, updated_at=_utcnow())
    )


async def get_unidades_by_escaneo(
    session: AsyncSession,
    escaneo_id: uuid.UUID,
) -> list[UnidadLogicaORM]:
    result = await session.execute(
        select(UnidadLogicaORM).where(UnidadLogicaORM.escaneo_id == escaneo_id)
    )
    return list(result.scalars().all())


# ── reglas_negocio ────────────────────────────────────────────────

async def create_reglas_negocio(
    session: AsyncSession,
    *,
    unidad_logica_id: uuid.UUID,
    activo_id: uuid.UUID,
    aplicacion_id: uuid.UUID,
    reglas: list[dict],
) -> None:
    for regla in reglas:
        if isinstance(regla, str):
            descripcion = regla
            codigo = None
        else:
            descripcion = regla.get("descripcion") or ""
            codigo = regla.get("codigo_relacionado")
            if isinstance(codigo, list):
                codigo = "\n".join(str(c) for c in codigo)
        if not descripcion:
            continue
        session.add(ReglaNegocioORM(
            unidad_logica_id=unidad_logica_id,
            activo_id=activo_id,
            aplicacion_id=aplicacion_id,
            descripcion=descripcion,
            codigo_relacionado=codigo,
            creado_por_ia=True,
        ))
    await session.flush()
