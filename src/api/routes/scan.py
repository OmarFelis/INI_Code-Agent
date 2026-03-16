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

from src.api.schemas.scan_request import ScanRequest, EnrichmentRequest
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
from src.core.enricher import llm_enricher
from src.core.integration.aone_client import AOneSyncClient
from src.core.analyzers.context_builder import ContextBuilder
from src.core.analyzers.worker_pool import _build_context_block
from src.config import settings
from src.models.domain import (
    ArchivoFuente,
    ProjectAnalysis,
    FileAnalysis,
    LanguageType,
    ProjectManifest,
    UnidadLogica,
)

logger = structlog.get_logger()

from src.api.dependencies.auth import verify_api_token

router = APIRouter(
    prefix="/api/v1/scan", 
    tags=["scan"],
    dependencies=[Depends(verify_api_token)]
)


def _build_results(result, request=None) -> dict:
    """Convert PipelineResult into a serializable dict."""
    archivos = []
    
    # Obtenemos los IDs y datos del request si existen, si no intentamos sacarlos del result
    activo_id = getattr(request, 'activo_id', None) or getattr(result, 'activo_id', None)
    aplicacion_id = getattr(request, 'aplicacion_id', None) or getattr(result, 'aplicacion_id', None)
    microservice_name = getattr(request, 'microservice_name', None) or getattr(result, 'microservice_name', None)

    for a in result.archivos:
        meta = json.loads(a.metadata) if getattr(a, 'metadata', None) else {}
        
        archivos.append({
            "nombre": a.nombre,
            "ruta_archivo": getattr(a, 'ruta_archivo', None) or a.nombre,
            "proposito": a.proposito,
            "capa": a.capa,
            "lenguaje": a.lenguaje,
            "total_funciones": getattr(a, 'total_funciones', 0) or 0,
            "total_clases": getattr(a, 'total_clases', 0) or 0,
            "endpoints": getattr(a, 'endpoints', 0) or 0,
            "operaciones_bd": getattr(a, 'operaciones_bd', 0) or 0,
            "llamadas_externas": getattr(a, 'llamadas_externas', 0) or 0,
            "complejidad_ciclomatica": getattr(a, 'complejidad_ciclomatica', None),
            "lineas_codigo": getattr(a, 'lineas_codigo', None),
            "metadata": meta,
            "commit_hash": getattr(a, 'commit_hash', None),
            "build_number": getattr(request, 'build_number', getattr(result, 'build_number', None)),
            "escaneado_en": datetime.now(timezone.utc).isoformat(),
            "activo": True,
            "activo_id": activo_id,
            "aplicacion_id": aplicacion_id
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
        meta = json.loads(u.metadata) if getattr(u, 'metadata', None) else {}
        unidades.append({
            "nombre": u.nombre,
            "tipo": u.tipo,
            "archivo": "",  # Will be filled below
            "parent": getattr(u, 'parent_id', None).replace("TEMP_CLASS_", "") if getattr(u, 'parent_id', None) else None,
            "linea_inicio": getattr(u, 'linea_inicio', None),
            "linea_fin": getattr(u, 'linea_fin', None),
            "complejidad": getattr(u, 'complejidad', None),
            "lineas_codigo": getattr(u, 'lineas_codigo', None),
            "accede_bd": getattr(u, 'accede_bd', False),
            "llamadas_externas": getattr(u, 'llamadas_externas', 0),
            "docstring": getattr(u, 'docstring', False),
            "overall_score": meta.get("overall_score"),
            "risk_level": meta.get("risk_level"),
            "metadata": meta,
            "resumen": None, # Will be filled if IA enrichment exists
            "modifica_estado": None,
            "auto_clasificado": False,
            "activo": True,
            "activo_id": activo_id,
            "aplicacion_id": aplicacion_id
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
        "microservice_name": microservice_name,
        "archivos_total": getattr(result, 'processed_files', sum(1 for a in result.archivos)),
        "funciones_total": sum(1 for u in result.unidades if u.tipo == "FUNCION"),
        "clases_total": sum(1 for u in result.unidades if u.tipo == "CLASE"),
        "lineas_total": sum(getattr(a, 'lineas_codigo', 0) or 0 for a in result.archivos),
        "commit_hash": getattr(result.archivos[0], 'commit_hash', None) if result.archivos else None,
        "metricas": {
            "languages": langs,
            "risk_distribution": risk_dist,
            "avg_complexity": round(sum(complexities) / len(complexities), 1) if complexities else 0,
            "max_complexity": max(complexities) if complexities else 0,
        },
        "arquitectura": {
            "capas": capas
        },
        "seguridad": None,
        "negocio": None,
        "dominios_negocio": None,
        "cumplimiento": None,
        "rendimiento": None,
        "escaneado_en": datetime.now().isoformat(),
        "activo": True,
        "activo_id": activo_id,
        "aplicacion_id": aplicacion_id
    }

    return {
        "escaneo": escaneo,
        "archivos_fuente": archivos,
        "unidades_logicas": unidades,
    }


async def _run_scan_background_task(job_id: UUID, request: ScanRequest):
    """Background task that runs the pipeline and writes to normalized tables."""
    from src.core.analyzers.pipeline import run as run_pipeline
    from src.core.scm.scm_adapter import clone_repository, cleanup_repository, get_commit_hash

    log = logger.bind(job_id=str(job_id), microservice=request.microservice_name)
    log.info("background_scan_started")

    async with async_session_factory() as session:
        temp_repo_path = None
        try:
            await repository.update_scan_job_status(session, job_id, status="RUNNING")
            await session.commit()

            project_path_to_scan = request.project_path

            if request.repo_url:
                temp_repo_path = os.path.abspath(f"tmp_repos/{job_id}")
                log.info("cloning_repository", repo_url=request.repo_url)
                await clone_repository(request.repo_url, temp_repo_path)
                project_path_to_scan = temp_repo_path

            # ── Idempotency check ─────────────────────────────────
            commit_hash = get_commit_hash(project_path_to_scan)
            if commit_hash and request.microservice_name:
                existing = await repository.find_completed_scan_by_commit(
                    session,
                    activo_id=request.activo_id,
                    microservice_name=request.microservice_name,
                    commit_hash=commit_hash,
                )
                if existing:
                    log.info(
                        "scan_skipped_already_exists",
                        existing_job_id=str(existing.id),
                        commit_hash=commit_hash,
                    )
                    if temp_repo_path and os.path.exists(temp_repo_path):
                        cleanup_repository(temp_repo_path)
                        temp_repo_path = None
                    await repository.update_scan_job_status(
                        session, job_id, status="SKIPPED",
                        error_message=f"Duplicate of completed scan {existing.id} at commit {commit_hash}"
                    )
                    await session.commit()
                    return

            result = await run_pipeline(
                project_path=project_path_to_scan,
                activo_id=request.activo_id,
                aplicacion_id=request.aplicacion_id,
                microservice_name=request.microservice_name,
                aone_client=None,
            )

            # Move repo to cache
            final_project_path = project_path_to_scan
            if temp_repo_path and os.path.exists(temp_repo_path):
                import shutil
                cache_dir = os.path.abspath(f"{settings.repos_cache_dir}/{job_id}")
                os.makedirs(os.path.dirname(cache_dir), exist_ok=True)
                shutil.move(temp_repo_path, cache_dir)
                final_project_path = cache_dir
                temp_repo_path = None
                log.info("repo_moved_to_cache", cache_path=cache_dir)

            # ── Build aggregated stats ────────────────────────────
            results_dict = _build_results(result, request=request)
            escaneo_data = results_dict["escaneo"]
            archivos_data = results_dict["archivos_fuente"]
            unidades_data = results_dict["unidades_logicas"]

            # ── Update escaneo row ────────────────────────────────
            await repository.update_scan_job_status(
                session,
                job_id,
                status="COMPLETED",
                total_files=result.total_files,
                processed_files=result.processed_files,
                failed_files=result.failed_files if result.failed_files else None,
                project_path=final_project_path,
                commit_hash=commit_hash,
            )

            # ── Insert archivos_fuente ────────────────────────────
            archivo_orm_map: dict[str, UUID] = {}  # nombre -> id
            escaneado_en = datetime.now()
            for a in archivos_data:
                orm = await repository.create_archivo_fuente(
                    session,
                    escaneo_id=job_id,
                    activo_id=request.activo_id,
                    aplicacion_id=request.aplicacion_id,
                    nombre=a["nombre"],
                    ruta_archivo=a.get("ruta_archivo"),
                    proposito=a.get("proposito"),
                    capa=a.get("capa"),
                    lenguaje=a.get("lenguaje"),
                    total_funciones=a.get("total_funciones", 0),
                    total_clases=a.get("total_clases", 0),
                    endpoints=a.get("endpoints", 0),
                    operaciones_bd=a.get("operaciones_bd", 0),
                    llamadas_externas=a.get("llamadas_externas", 0),
                    complejidad_ciclomatica=a.get("complejidad_ciclomatica"),
                    lineas_codigo=a.get("lineas_codigo"),
                    metadata=a.get("metadata"),
                    commit_hash=a.get("commit_hash"),
                    build_number=a.get("build_number"),
                    escaneado_en=escaneado_en,
                )
                archivo_orm_map[a["nombre"]] = orm.id

            # ── Insert unidades_logicas ───────────────────────────
            # First pass: insert CLASEs, build class name -> id map
            clase_id_map: dict[str, UUID] = {}
            for u in unidades_data:
                if u["tipo"] != "CLASE":
                    continue
                meta = u.get("metadata", {})
                orm = await repository.create_unidad_logica(
                    session,
                    escaneo_id=job_id,
                    activo_id=request.activo_id,
                    aplicacion_id=request.aplicacion_id,
                    archivo_id=archivo_orm_map.get(u["archivo"]),
                    nombre=u["nombre"],
                    tipo=u["tipo"],
                    linea_inicio=u.get("linea_inicio"),
                    linea_fin=u.get("linea_fin"),
                    complejidad=u.get("complejidad"),
                    lineas_codigo=u.get("lineas_codigo"),
                    accede_bd=u.get("accede_bd", False),
                    llamadas_externas=u.get("llamadas_externas", 0),
                    docstring=u.get("docstring", False),
                    overall_score=u.get("overall_score"),
                    risk_level=u.get("risk_level"),
                    metadata=meta,
                )
                clase_id_map[u["nombre"]] = orm.id

            # Second pass: insert FUNCIONes with parent_id resolved
            for u in unidades_data:
                if u["tipo"] != "FUNCION":
                    continue
                meta = u.get("metadata", {})
                parent_name = u.get("parent")
                await repository.create_unidad_logica(
                    session,
                    escaneo_id=job_id,
                    activo_id=request.activo_id,
                    aplicacion_id=request.aplicacion_id,
                    archivo_id=archivo_orm_map.get(u["archivo"]),
                    parent_id=clase_id_map.get(parent_name) if parent_name else None,
                    nombre=u["nombre"],
                    tipo=u["tipo"],
                    linea_inicio=u.get("linea_inicio"),
                    linea_fin=u.get("linea_fin"),
                    complejidad=u.get("complejidad"),
                    lineas_codigo=u.get("lineas_codigo"),
                    accede_bd=u.get("accede_bd", False),
                    llamadas_externas=u.get("llamadas_externas", 0),
                    docstring=u.get("docstring", False),
                    overall_score=u.get("overall_score"),
                    risk_level=u.get("risk_level"),
                    metadata=meta,
                )

            await session.commit()

            sync_client = AOneSyncClient()
            try:
                await sync_client.sync_scan_results(results_dict)
            except Exception as sync_e:
                log.error("aone_sync_failed", error=repr(sync_e))
            finally:
                await sync_client.close()

            log.info(
                "background_scan_completed",
                archivos=result.processed_files,
                clases=escaneo_data["clases_total"],
                funciones=escaneo_data["funciones_total"],
                score=result.score_general,
            )

        except Exception as e:
            log.error("background_scan_failed", error=repr(e))
            try:
                await repository.update_scan_job_status(
                    session, job_id, status="FAILED",
                    failed_files=[{"archivo": "ALL", "error": str(e)}]
                )
                await session.commit()
            except Exception as e_inner:
                log.error("background_scan_failed_to_update_status", error=str(e_inner))
        finally:
            if temp_repo_path and os.path.exists(temp_repo_path):
                cleanup_repository(temp_repo_path)


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

    # Validate domain allowed if repo_url is passed
    if request.repo_url:
        from urllib.parse import urlparse
        from src.config import settings
        
        parsed_url = urlparse(request.repo_url)
        domain = parsed_url.netloc.split(':')[0]
        allowed_domains = [d.strip() for d in settings.allowed_git_domains.split(',')]
        
        if not any(domain.endswith(d) for d in allowed_domains):
            raise HTTPException(
                status_code=403,
                detail=f"Domain '{domain}' is not in the allowed list: {settings.allowed_git_domains}"
            )
            
    # Validate project_path exists locally tracking git
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

    archivos_orm = await repository.get_archivos_by_escaneo(session, uuid_id)
    unidades_orm = await repository.get_unidades_by_escaneo(session, uuid_id)

    return {
        "job_id": str(job.id),
        "status": job.status,
        "microservice_name": job.microservice_name,
        "project_path": job.project_path,
        "total_files": job.total_files,
        "processed_files": job.processed_files,
        "created_at": job.created_at,
        "archivos_fuente": [
            {
                "id": str(a.id),
                "nombre": a.nombre,
                "ruta_archivo": a.ruta_archivo,
                "capa": a.capa,
                "lenguaje": a.lenguaje,
                "proposito": a.proposito,
                "total_funciones": a.total_funciones,
                "total_clases": a.total_clases,
                "endpoints": a.endpoints,
                "operaciones_bd": a.operaciones_bd,
                "llamadas_externas": a.llamadas_externas,
                "complejidad_ciclomatica": a.complejidad_ciclomatica,
                "lineas_codigo": a.lineas_codigo,
                "metadata": a.meta,
                "commit_hash": a.commit_hash,
                "analisis_ia": a.analisis_ia,
            }
            for a in archivos_orm
        ],
        "unidades_logicas": [
            {
                "id": str(u.id),
                "nombre": u.nombre,
                "tipo": u.tipo,
                "archivo_id": str(u.archivo_id) if u.archivo_id else None,
                "parent_id": str(u.parent_id) if u.parent_id else None,
                "linea_inicio": u.linea_inicio,
                "linea_fin": u.linea_fin,
                "complejidad": u.complejidad,
                "lineas_codigo": u.lineas_codigo,
                "accede_bd": u.accede_bd,
                "llamadas_externas": u.llamadas_externas,
                "docstring": u.docstring,
                "overall_score": float(u.overall_score) if u.overall_score else None,
                "risk_level": u.risk_level,
                "metadata": u.meta,
                "analisis_ia": u.analisis_ia,
            }
            for u in unidades_orm
        ],
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

async def _run_enrichment_background_task(job_id: UUID, request: EnrichmentRequest):
    """Background task to extract code and run AI enrichment."""
    log = logger.bind(job_id=str(job_id), task="ai_enrichment")
    
    try:
        async with async_session_factory() as session:
            job = await repository.get_scan_job(session, job_id)
            if not job or not job.results:
                log.error("enrichment_job_not_found_or_empty")
                return
            
            project_path = job.project_path
            
            archivos_fuente = job.results.get("archivos_fuente", [])
            mapa_archivos = {a.get("nombre"): a.get("ruta_archivo") for a in archivos_fuente}
            
            unidades = job.results.get("unidades_logicas", [])
            payload_funciones = []
            
            for func_req in request.funciones:
                unit = next((u for u in unidades if u.get("nombre") == func_req.nombre and u.get("archivo") == func_req.archivo), None)
                if not unit:
                    log.warning("enrichment_unit_not_found", function=func_req.nombre, file=func_req.archivo)
                    continue
                
                ruta_relativa = mapa_archivos.get(func_req.archivo)
                if not ruta_relativa:
                    log.warning("enrichment_file_path_not_found", file=func_req.archivo)
                    continue
                    
                archivo_absoluto = os.path.join(project_path, ruta_relativa)
                
                try:
                    with open(archivo_absoluto, "r", encoding="utf-8") as file_source:
                        lines = file_source.readlines()
                        inicio = unit.get("linea_inicio", 1) - 1
                        fin = unit.get("linea_fin", len(lines))
                        
                        codigo_original = "".join(lines[inicio:fin])
                        
                        payload_funciones.append({
                            "nombre_funcion": unit.get("nombre"),
                            "componente": unit.get("parent") or "Standalone",
                            "archivo": ruta_relativa,
                            "lineas": f"{inicio+1}-{fin}",
                            "codigo_original": codigo_original
                        })
                except Exception as e:
                    log.error("enrichment_file_read_error", file=archivo_absoluto, error=str(e))
                    continue
                    
            if not payload_funciones:
                log.error("enrichment_no_code_extracted")
                return
                
            log.info("enrichment_calling_bedrock", functions=len(payload_funciones))
            resultados_ia = await llm_enricher.analyze_functions_batch(payload_funciones)
            
            ia_lookup = {(r.get("nombre_funcion"), r.get("archivo")): r.get("analisis_ia") for r in resultados_ia}
            
            # Map back to units
            for unit in unidades:
                ruta_rel = mapa_archivos.get(unit.get("archivo"))
                key = (unit.get("nombre"), ruta_rel)
                if key in ia_lookup:
                    unit["analisis_ia"] = ia_lookup[key]

            # Save modified results back to DB
            await repository.update_scan_job_status(
                session,
                job_id,
                status=job.status, 
                results=job.results
            )
            await session.commit()
            
            # Sincronización a A-ONE DB
            sync_client = AOneSyncClient()
            try:
                await sync_client.sync_scan_results(job.results)
            except Exception as sync_e:
                log.error("aone_sync_failed_enrich", error=repr(sync_e))
            finally:
                await sync_client.close()
                
            log.info("enrichment_completed_successfully")

    except Exception as e:
        log.error("background_enrichment_failed", error=str(e))


@router.post(
    "/{job_id}/enrich",
    status_code=202,
    summary="Enrich specific functions using AI",
    description="Extracts source code and sends it to AWS Bedrock for business rule extraction.",
)
async def enrich_scan_job(
    job_id: str,
    request: EnrichmentRequest,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
):
    """Enrich selected functions of a completed scan job."""
    try:
        uuid_id = UUID(job_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid job_id format — expected UUID")

    job = await repository.get_scan_job(session, uuid_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Scan job not found: {job_id}")

    if job.status != "COMPLETED":
        raise HTTPException(status_code=400, detail="Scan job must be COMPLETED before enrichment.")

    background_tasks.add_task(_run_enrichment_background_task, uuid_id, request)
    
    return {"message": "Enrichment job queued successfully", "job_id": job_id}


# ── Enrich-All (todas las funciones) ─────────────────────────────

async def _run_enrich_all_background_task(job_id: UUID):
    """Enrich ALL functions — UPDATE analisis_ia directly in unidades_logicas."""
    log = logger.bind(job_id=str(job_id), task="ai_enrich_all")

    try:
        async with async_session_factory() as session:
            job = await repository.get_scan_job(session, job_id)
            if not job:
                log.error("enrich_all_job_not_found")
                return

            project_path = job.project_path
            archivos_orm = await repository.get_archivos_by_escaneo(session, job_id)
            unidades_orm = await repository.get_unidades_by_escaneo(session, job_id)

            # Build context
            archivos_data = [
                {"nombre": a.nombre, "ruta_archivo": a.ruta_archivo,
                 "lenguaje": a.lenguaje, "capa": a.capa, "lineas_codigo": a.lineas_codigo}
                for a in archivos_orm
            ]
            project_context = None
            if settings.enable_context_enrichment:
                project_context = _rebuild_project_context(job.microservice_name or "unknown", archivos_data)
                log.info("enrich_all_context_built", modules=len(project_context.manifest.modules))

            mapa_archivos = {a.nombre: a.ruta_archivo for a in archivos_orm}
            payload_funciones = []
            unidades_pendientes = [
                u for u in unidades_orm
                if u.tipo in ("FUNCION", "CLASE") and (
                    not u.analisis_ia or "error" in u.analisis_ia
                )
            ]

            for unit in unidades_pendientes:
                ruta_relativa = mapa_archivos.get(unit.nombre) or next(
                    (a.ruta_archivo for a in archivos_orm if a.id == unit.archivo_id), None
                )
                if not ruta_relativa:
                    continue
                archivo_absoluto = os.path.join(project_path, ruta_relativa)
                try:
                    with open(archivo_absoluto, "r", encoding="utf-8") as f:
                        lines = f.readlines()
                        inicio = (unit.linea_inicio or 1) - 1
                        fin = unit.linea_fin or len(lines)
                        codigo_original = "".join(lines[inicio:fin])

                    context_block = ""
                    if project_context:
                        file_ctx = project_context.file_contexts.get(ruta_relativa)
                        context_block = _build_context_block(project_context.manifest, file_ctx)

                    esquema_clase = unit.nombre
                    if context_block:
                        esquema_clase = f"{context_block}\n\nClase/Componente: {esquema_clase}"

                    payload_funciones.append({
                        "_unidad_id": str(unit.id),
                        "nombre_funcion": unit.nombre,
                        "tipo_unidad": "clase" if unit.tipo == "CLASE" else "función",
                        "componente": esquema_clase,
                        "archivo": ruta_relativa,
                        "codigo_original": codigo_original,
                    })
                except Exception as e:
                    log.warning("enrich_all_file_read_error", file=archivo_absoluto, error=str(e))

            if not payload_funciones:
                log.warning("enrich_all_no_functions_to_enrich")
                return

            resultados_ia = await llm_enricher.analyze_functions_batch(payload_funciones)

            # UPDATE each unidad directly
            for idx, res in enumerate(resultados_ia):
                unidad_id_str = payload_funciones[idx].get("_unidad_id")
                if unidad_id_str and res.get("analisis_ia"):
                    await repository.update_unidad_analisis_ia(
                        session, UUID(unidad_id_str), res["analisis_ia"]
                    )
                    reglas = res["analisis_ia"].get("reglas_de_negocio") or []
                    if reglas:
                        unidad = next((u for u in unidades_orm if str(u.id) == unidad_id_str), None)
                        if unidad:
                            await repository.create_reglas_negocio(
                                session,
                                unidad_logica_id=unidad.id,
                                activo_id=unidad.activo_id,
                                aplicacion_id=unidad.aplicacion_id,
                                reglas=reglas,
                            )

            await session.commit()
            log.info("enrich_all_completed", enriched=len(resultados_ia))

    except Exception as e:
        log.error("enrich_all_failed", error=repr(e))


@router.post(
    "/{job_id}/enrich-all",
    status_code=202,
    summary="Enrich ALL functions using AI",
    description="Extracts source code of ALL functions and sends them to AWS Bedrock for business rule extraction.",
)
async def enrich_all_functions(
    job_id: str,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
):
    """Enrich ALL functions of a completed scan job."""
    try:
        uuid_id = UUID(job_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid job_id format — expected UUID")

    job = await repository.get_scan_job(session, uuid_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Scan job not found: {job_id}")
    if job.status != "COMPLETED":
        raise HTTPException(status_code=400, detail="Scan job must be COMPLETED before enrichment.")

    background_tasks.add_task(_run_enrich_all_background_task, uuid_id)

    unidades_orm = await repository.get_unidades_by_escaneo(session, uuid_id)
    total_functions = sum(1 for u in unidades_orm if u.tipo == "FUNCION")
    return {"message": f"Enrich-all queued for {total_functions} functions", "job_id": job_id}


# ── Enrich-Files (todos los archivos) ────────────────────────────

async def _run_enrich_files_background_task(job_id: UUID):
    """Enrich ALL files — UPDATE analisis_ia directly in archivos_fuente."""
    log = logger.bind(job_id=str(job_id), task="ai_enrich_files")

    try:
        async with async_session_factory() as session:
            job = await repository.get_scan_job(session, job_id)
            if not job:
                log.error("enrich_files_job_not_found")
                return

            project_path = job.project_path
            archivos_orm = await repository.get_archivos_by_escaneo(session, job_id)

            archivos_data = [
                {"nombre": a.nombre, "ruta_archivo": a.ruta_archivo,
                 "lenguaje": a.lenguaje, "capa": a.capa, "lineas_codigo": a.lineas_codigo}
                for a in archivos_orm
            ]
            project_context = None
            if settings.enable_context_enrichment:
                project_context = _rebuild_project_context(job.microservice_name or "unknown", archivos_data)
                log.info("enrich_files_context_built", modules=len(project_context.manifest.modules))

            payload_archivos = []
            archivos_pendientes = [a for a in archivos_orm if not a.analisis_ia or "error" in a.analisis_ia]

            for archivo in archivos_pendientes:
                ruta_relativa = archivo.ruta_archivo
                if not ruta_relativa:
                    continue
                archivo_absoluto = os.path.join(project_path, ruta_relativa)
                try:
                    with open(archivo_absoluto, "r", encoding="utf-8") as f:
                        codigo_completo = f.read()

                    context_block = ""
                    if project_context:
                        file_ctx = project_context.file_contexts.get(ruta_relativa)
                        context_block = _build_context_block(project_context.manifest, file_ctx)

                    payload_archivos.append({
                        "_archivo_id": str(archivo.id),
                        "nombre_archivo": archivo.nombre,
                        "ruta_archivo": ruta_relativa,
                        "lenguaje": archivo.lenguaje or "Desconocido",
                        "capa": archivo.capa or "Sin clasificar",
                        "codigo_completo": codigo_completo,
                        "contexto_proyecto": context_block,
                    })
                except Exception as e:
                    log.warning("enrich_files_read_error", file=archivo_absoluto, error=str(e))

            if not payload_archivos:
                log.warning("enrich_files_no_files_to_enrich")
                return

            has_context = any(p.get("contexto_proyecto") for p in payload_archivos)
            if has_context:
                resultados_ia = await llm_enricher.analyze_files_batch_with_context(payload_archivos)
            else:
                resultados_ia = await llm_enricher.analyze_files_batch(payload_archivos)

            # UPDATE each archivo directly
            for idx, res in enumerate(resultados_ia):
                archivo_id_str = payload_archivos[idx].get("_archivo_id")
                if archivo_id_str and res.get("analisis_ia"):
                    await repository.update_archivo_analisis_ia(
                        session, UUID(archivo_id_str), res["analisis_ia"]
                    )

            await session.commit()
            log.info("enrich_files_completed", enriched=len(resultados_ia))

    except Exception as e:
        log.error("enrich_files_failed", error=repr(e))


@router.post(
    "/{job_id}/enrich-files",
    status_code=202,
    summary="Enrich ALL files using AI",
    description="Reads full source code of ALL files and sends them to AWS Bedrock for file-level analysis.",
)
async def enrich_all_files(
    job_id: str,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
):
    """Enrich ALL files of a completed scan job with file-level AI analysis."""
    try:
        uuid_id = UUID(job_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid job_id format — expected UUID")

    job = await repository.get_scan_job(session, uuid_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Scan job not found: {job_id}")
    if job.status != "COMPLETED":
        raise HTTPException(status_code=400, detail="Scan job must be COMPLETED before enrichment.")

    background_tasks.add_task(_run_enrich_files_background_task, uuid_id)

    archivos_orm = await repository.get_archivos_by_escaneo(session, uuid_id)
    total_files = len(archivos_orm)
    return {"message": f"Enrich-files queued for {total_files} files", "job_id": job_id}


# ── Helper: Rebuild ProjectContext from stored scan results ──────

def _rebuild_project_context(microservice_name: str, archivos_fuente: list[dict]):
    """
    Rebuild a lightweight ProjectContext from the stored scan results.
    This allows the enrich endpoints to inject context without re-running
    the full pipeline.
    """
    from src.models.domain import ProjectContext, ProjectManifest, FileContext
    from pathlib import PurePosixPath
    from collections import defaultdict

    # Build fake FileAnalysis list for the ContextBuilder
    fake_files = []
    for a in archivos_fuente:
        ruta = a.get("ruta_archivo", a.get("nombre", ""))
        lang_str = a.get("lenguaje", "Python")
        try:
            lang = LanguageType(lang_str)
        except ValueError:
            lang = LanguageType.PYTHON

        fa = FileAnalysis(
            file_path=ruta,
            file_name=a.get("nombre", ""),
            language=lang,
            total_lines=a.get("lineas_codigo", 0),
            imports=a.get("imports", []),
        )
        fake_files.append(fa)

    fake_archivos = []
    for a in archivos_fuente:
        fake_archivos.append(ArchivoFuente(
            activo_id="rebuild",
            aplicacion_id="rebuild",
            nombre=a.get("nombre", ""),
            ruta_archivo=a.get("ruta_archivo"),
            capa=a.get("capa"),
            lenguaje=a.get("lenguaje"),
        ))

    project_analysis = ProjectAnalysis(
        project_name=microservice_name,
        project_path="",
        files=fake_files,
        total_files=len(fake_files),
        total_lines=sum(a.get("lineas_codigo", 0) for a in archivos_fuente),
        languages={},
    )

    # Count languages
    for a in archivos_fuente:
        lang = a.get("lenguaje", "Unknown")
        project_analysis.languages[lang] = project_analysis.languages.get(lang, 0) + 1

    builder = ContextBuilder()
    return builder.build(project_analysis, fake_archivos, [])

