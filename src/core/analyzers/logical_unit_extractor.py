"""
Code-Agent — Logical Unit Extractor.
Transforms FileAnalysis → ArchivoFuente + List[UnidadLogica] with correct hierarchy.
Includes scoring logic (overall_score, risk_level, architecture layer classification).
"""

import json
from pathlib import Path

import structlog

from src.core.analyzers.factory import get_analyzer
from src.models.domain import (
    ArchivoFuente,
    FileAnalysis,
    UnidadLogica,
    UnitMetadata,
    ArchitectureLayer,
    RiskLevel,
)

logger = structlog.get_logger()

# ── Infrastructure import patterns for layer classification ───────────

INFRA_IMPORTS_PYTHON = {
    "psycopg2", "sqlalchemy", "pymongo", "redis", "asyncpg", "databases",
    "boto3", "botocore", "dynamodb", "s3", "sqs", "sns",
    "kafka", "pika", "celery",
}

ADAPTOR_IMPORTS_PYTHON = {
    "fastapi", "flask", "django", "starlette", "sanic", "aiohttp",
    "uvicorn", "gunicorn",
}

INFRA_IMPORTS_JAVA = {
    "java.sql", "javax.sql", "org.hibernate", "javax.persistence",
    "jakarta.persistence", "org.springframework.data",
    "com.amazonaws", "software.amazon",
    "org.springframework.kafka", "org.springframework.jms",
}

ADAPTOR_IMPORTS_JAVA = {
    "org.springframework.web", "javax.servlet", "jakarta.servlet",
    "org.springframework.stereotype.Controller",
    "org.springframework.web.bind.annotation",
}

INFRA_IMPORTS_JS = {
    "mongoose", "sequelize", "knex", "prisma", "typeorm",
    "aws-sdk", "@aws-sdk", "redis", "ioredis",
}

ADAPTOR_IMPORTS_JS = {
    "express", "koa", "hapi", "fastify", "nest",
}


def extract(
    file_analysis: FileAnalysis,
    file_path_absolute: str,
    activo_id: str,
    aplicacion_id: str,
) -> tuple[ArchivoFuente, list[UnidadLogica]]:
    """
    Extract ArchivoFuente + List[UnidadLogica] from a FileAnalysis.

    Returns:
        Tuple of (ArchivoFuente, list of UnidadLogica with hierarchy).
        The UnidadLogica list has classes first, then functions with parent_id set.
    """
    # ── 1. Classify architecture layer for the file ───────────
    file_layer = _classify_layer(file_analysis.imports, file_analysis.language.value)

    # ── 2. Build ArchivoFuente ────────────────────────────────
    archivo = ArchivoFuente(
        activo_id=activo_id,
        aplicacion_id=aplicacion_id,
        nombre=file_analysis.file_name,
        ruta_archivo=file_analysis.file_path,
        proposito=_detect_proposito(file_analysis),
        capa=file_layer.value,
        lenguaje=file_analysis.language.value,
        total_funciones=len([f for f in file_analysis.functions]),
        total_clases=len(file_analysis.classes),
        endpoints=len(file_analysis.api_endpoints),
        operaciones_bd=len(file_analysis.database_calls),
        llamadas_externas=len(file_analysis.external_calls),
        complejidad_ciclomatica=file_analysis.complexity,
        lineas_codigo=file_analysis.total_lines,
        metadata=json.dumps({
            "imports": file_analysis.imports,
            "decorators": file_analysis.decorators,
            "api_endpoints_detail": file_analysis.api_endpoints,
            "database_calls_detail": file_analysis.database_calls,
            "external_calls_detail": file_analysis.external_calls,
        }),
    )

    # ── 3. Get per-function details from analyzer ─────────────
    analyzer = get_analyzer(file_path_absolute)
    if analyzer and hasattr(analyzer, "get_function_details"):
        func_details = analyzer.get_function_details(file_path_absolute)
    else:
        func_details = _fallback_details(file_analysis)

    # ── 4. Build UnidadLogica list with hierarchy ─────────────
    unidades: list[UnidadLogica] = []
    class_temp_ids: dict[str, str] = {}  # class_name → temp placeholder id

    has_db_calls = len(file_analysis.database_calls) > 0
    has_infra_imports = _has_infra_imports(file_analysis.imports, file_analysis.language.value)

    # First pass: classes
    for detail in func_details:
        if detail["type"] == "CLASE":
            # Score for class will be calculated after its methods
            temp_id = f"TEMP_CLASS_{detail['name']}"
            class_temp_ids[detail["name"]] = temp_id

            unidad = _build_unidad(
                detail=detail,
                parent_id=None,
                activo_id=activo_id,
                aplicacion_id=aplicacion_id,
                layer=file_layer,
                has_db=has_db_calls,
                has_infra=has_infra_imports,
            )
            unidades.append(unidad)

    # Second pass: functions
    child_scores: dict[str, list[float]] = {}  # class_name → list of child scores
    child_complexities: dict[str, list[int]] = {}

    for detail in func_details:
        if detail["type"] == "FUNCION":
            parent_id = class_temp_ids.get(detail.get("parent")) if detail.get("parent") else None

            unidad = _build_unidad(
                detail=detail,
                parent_id=parent_id,
                activo_id=activo_id,
                aplicacion_id=aplicacion_id,
                layer=file_layer,
                has_db=has_db_calls,
                has_infra=has_infra_imports,
            )
            unidades.append(unidad)

            # Track scores for class averaging
            if detail.get("parent"):
                parent_name = detail["parent"]
                meta = json.loads(unidad.metadata) if unidad.metadata else {}
                score = meta.get("overall_score", 0)
                complexity = detail.get("complejidad", 1)

                if parent_name not in child_scores:
                    child_scores[parent_name] = []
                    child_complexities[parent_name] = []
                child_scores[parent_name].append(score)
                child_complexities[parent_name].append(complexity)

    # Third pass: update class scores
    for unidad in unidades:
        if unidad.tipo != "CLASE":
            continue

        meta = json.loads(unidad.metadata) if unidad.metadata else {}

        if unidad.nombre in child_scores:
            # Class WITH methods → score = average of children
            avg_score = sum(child_scores[unidad.nombre]) / len(child_scores[unidad.nombre])
            max_complexity = max(child_complexities[unidad.nombre])
            risk = _calc_risk(max_complexity, avg_score)

            meta["overall_score"] = round(avg_score, 2)
            meta["risk_level"] = risk.value
            unidad.metadata = json.dumps(meta)
            unidad.complejidad = max_complexity
        else:
            # Class WITHOUT methods (DTO, schema, model, enum, dataclass)
            # These are simple data containers — give them a high score
            loc = unidad.lineas_codigo or 0
            complexity = unidad.complejidad or 1

            # DTOs are inherently atomic and transparent
            # Penalize slightly for very large DTOs (> 50 fields)
            dto_score = 95.0
            if loc > 100:
                dto_score -= 10.0  # Large DTO
            elif loc > 50:
                dto_score -= 5.0   # Medium DTO
            if complexity > 3:
                dto_score -= 5.0   # Has validators or computed fields

            dto_score = max(dto_score, 70.0)
            risk = _calc_risk(complexity, dto_score)

            meta["overall_score"] = round(dto_score, 2)
            meta["risk_level"] = risk.value
            meta["class_type"] = "DTO"
            unidad.metadata = json.dumps(meta)

    return archivo, unidades


# ── Scoring ───────────────────────────────────────────────────────────

def _calc_score(loc: int, complexity: int, has_db: bool, has_infra: bool) -> float:
    """
    Calculate overall_score for a function.
    Formula: (atomicity × 0.4 + transparency × 0.4 + complexity_score × 0.2) × 100
    """
    # Atomicity (40%) — is the function small and simple?
    atomicity = 1.0
    if loc > 30:
        atomicity -= 0.3
    if complexity > 10:
        atomicity -= 0.3
    atomicity = max(atomicity, 0.0)

    # Transparency (40%) — does it mix business logic with infrastructure?
    transparency = 1.0
    if has_db:
        transparency -= 0.4
    if has_infra:
        transparency -= 0.3
    transparency = max(transparency, 0.0)

    # Complexity Score (20%) — inverse of cyclomatic complexity
    complexity_score = 1.0 / max(complexity, 1)

    return round((atomicity * 0.4 + transparency * 0.4 + complexity_score * 0.2) * 100, 2)


def _calc_risk(complexity: int, score: float) -> RiskLevel:
    """Calculate risk level from complexity and score."""
    if complexity > 15 or score < 50:
        return RiskLevel.HIGH
    if complexity >= 10 or score < 70:
        return RiskLevel.MEDIUM
    return RiskLevel.LOW


# ── Layer Classification ──────────────────────────────────────────────

def _classify_layer(imports: list[str], language: str) -> ArchitectureLayer:
    """Classify a file's architecture layer based on its imports."""
    imports_lower = {i.lower() for i in imports}

    if language in ("Python",):
        has_infra = any(any(inf in imp for inf in INFRA_IMPORTS_PYTHON) for imp in imports_lower)
        has_adaptor = any(any(adp in imp for adp in ADAPTOR_IMPORTS_PYTHON) for imp in imports_lower)
    elif language in ("Java",):
        has_infra = any(any(inf in imp for inf in INFRA_IMPORTS_JAVA) for imp in imports_lower)
        has_adaptor = any(any(adp in imp for adp in ADAPTOR_IMPORTS_JAVA) for imp in imports_lower)
    else:  # JavaScript / TypeScript
        has_infra = any(any(inf in imp for inf in INFRA_IMPORTS_JS) for imp in imports_lower)
        has_adaptor = any(any(adp in imp for adp in ADAPTOR_IMPORTS_JS) for imp in imports_lower)

    if has_infra:
        return ArchitectureLayer.INFRAESTRUCTURA
    if has_adaptor:
        return ArchitectureLayer.ADAPTADOR
    return ArchitectureLayer.DOMINIO


def _has_infra_imports(imports: list[str], language: str) -> bool:
    """Check if any imports indicate infrastructure coupling."""
    imports_lower = {i.lower() for i in imports}
    all_infra = INFRA_IMPORTS_PYTHON | INFRA_IMPORTS_JAVA | INFRA_IMPORTS_JS
    return any(any(inf in imp for inf in all_infra) for imp in imports_lower)


# ── Helpers ───────────────────────────────────────────────────────────

def _detect_proposito(fa: FileAnalysis) -> str:
    """Detect file purpose (VARCHAR 30) from patterns."""
    name = fa.file_name.lower()
    if any(k in name for k in ("controller", "handler", "route", "endpoint", "view")):
        return "Controller"
    if any(k in name for k in ("service", "usecase", "logic")):
        return "Service"
    if any(k in name for k in ("repository", "repo", "dao", "mapper")):
        return "Repository"
    if any(k in name for k in ("model", "entity", "schema", "dto")):
        return "Model"
    if any(k in name for k in ("config", "settings", "constant")):
        return "Config"
    if any(k in name for k in ("test", "spec")):
        return "Test"
    if any(k in name for k in ("util", "helper", "common")):
        return "Utility"
    if any(k in name for k in ("adapter", "client", "gateway")):
        return "Adapter"
    return "Module"


def _build_unidad(
    detail: dict,
    parent_id: str | None,
    activo_id: str,
    aplicacion_id: str,
    layer: ArchitectureLayer,
    has_db: bool,
    has_infra: bool,
) -> UnidadLogica:
    """Build a UnidadLogica from function detail dict."""
    loc = detail.get("lineas_codigo", 0)
    complexity = detail.get("complejidad", 1)

    if detail["type"] == "FUNCION":
        score = _calc_score(loc, complexity, has_db, has_infra)
        risk = _calc_risk(complexity, score)
    else:
        # Class score will be updated later as average of children
        score = 0.0
        risk = RiskLevel.LOW

    compliance = {
        "loc_ok": loc <= 30,
        "complexity_ok": complexity <= 10,
        "has_multi_layer_coupling": has_db and has_infra,
    }

    metadata = UnitMetadata(
        capa=layer.value,
        overall_score=score,
        risk_level=risk.value,
        compliance=compliance,
    )

    return UnidadLogica(
        archivo_id="",  # Will be set after ArchivoFuente is persisted
        parent_id=parent_id,
        activo_id=activo_id,
        aplicacion_id=aplicacion_id,
        nombre=detail["name"],
        tipo=detail["type"],
        linea_inicio=detail.get("linea_inicio"),
        linea_fin=detail.get("linea_fin"),
        complejidad=complexity,
        lineas_codigo=loc,
        accede_bd=has_db,
        llamadas_externas=0,
        docstring=detail.get("docstring", False),
        metadata=metadata.model_dump_json(),
    )


def _fallback_details(fa: FileAnalysis) -> list[dict]:
    """Fallback when analyzer doesn't support get_function_details."""
    details = []
    for cls in fa.classes:
        details.append({
            "name": cls, "type": "CLASE", "parent": None,
            "linea_inicio": 1, "linea_fin": fa.total_lines,
            "lineas_codigo": fa.total_lines, "complejidad": fa.complexity,
            "docstring": False,
        })
    for func in fa.functions:
        parts = func.split(".")
        name = parts[-1]
        parent = parts[0] if len(parts) > 1 else None
        details.append({
            "name": name, "type": "FUNCION", "parent": parent,
            "linea_inicio": 1, "linea_fin": 1,
            "lineas_codigo": max(fa.total_lines // max(len(fa.functions), 1), 1),
            "complejidad": fa.complexity,
            "docstring": False,
        })
    return details
