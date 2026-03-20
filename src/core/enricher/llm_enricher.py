import os
import re
import json
import asyncio
import boto3
import structlog
from typing import List, Dict

try:
    import json_repair
    HAS_JSON_REPAIR = True
except ImportError:
    HAS_JSON_REPAIR = False

logger = structlog.get_logger()

# Lazy-initialized LLM cache singleton
_llm_cache = None

def _get_cache():
    """Lazy init to avoid import-time side effects."""
    global _llm_cache
    if _llm_cache is None:
        from src.config import settings
        from src.core.enricher.llm_cache import LLMCache
        _llm_cache = LLMCache(
            ttl_days=settings.llm_cache_ttl_days,
        )
    return _llm_cache

# Configuración AWS Bedrock
REGION = "us-east-1"
MODEL_ID = "anthropic.claude-3-haiku-20240307-v1:0"

PROMPT_TACTICO = """
Eres un Arquitecto de Software Experto especializado en ingeniería inversa. 
Tu tarea es leer código fuente y extraer (1) un resumen funcional conciso y (2) las reglas de negocio explícitas.

<esquema_clase>
{esquema_clase}
</esquema_clase>

Analiza el siguiente {tipo_unidad} ({nombre_funcion}):
<codigo_fuente>
{codigo_original}
</codigo_fuente>

INSTRUCCIONES: Extrae reglas de negocio (condicionales) y un resumen funcional estructurado. Para cada regla, incluye la explicación y el fragmento de código (snippet) exacto que evalúa la condición.
Devuelve EXACTAMENTE este formato JSON purista sin bloques de markdown:
{{
  "resumen_funcional": "string en español",
  "modifica_estado": boolean,
  "reglas_de_negocio": [
    {{
      "descripcion": "explicación de la regla de negocio",
      "codigo_relacionado": "if (edad < 18) {{ throw Error... }}"
    }}
  ]
}}
"""

PROMPT_ARCHIVO = """
Eres un Arquitecto de Software Experto. Tu tarea es analizar un archivo de código fuente completo y generar un análisis estructurado.

Archivo: {nombre_archivo}
Lenguaje: {lenguaje}
Capa detectada: {capa}

<codigo_completo>
{codigo_completo}
</codigo_completo>

INSTRUCCIONES: Analiza el archivo completo y devuelve EXACTAMENTE este formato JSON purista sin bloques de markdown:
{{
  "resumen_archivo": "descripción concisa en español del propósito general del archivo",
  "responsabilidad_principal": "string corto: ej. Controlador REST, Servicio de negocio, Repositorio de datos, Modelo de dominio, Configuración, Utilidad",
  "dependencias_clave": ["lista de imports/dependencias críticas del archivo"],
  "patrones_detectados": ["ej. Singleton, Repository, Factory, Observer"],
  "endpoints_expuestos": [
    {{
      "metodo": "GET/POST/PUT/DELETE",
      "ruta": "/api/ejemplo",
      "descripcion": "breve descripción"
    }}
  ],
  "observaciones": ["notas relevantes sobre calidad, seguridad o mejoras"]
}}
"""

def get_bedrock_client():
    """Inicializa boto3 usando profile si está configurado, sino usa variables de entorno."""
    from src.config import settings
    try:
        session = boto3.Session(profile_name=settings.aws_profile) if settings.aws_profile else boto3.Session()
        return session.client('bedrock-runtime', region_name=REGION)
    except Exception as e:
        logger.error("error_initializing_bedrock", error=str(e), profile=settings.aws_profile)
        raise

def _sanitize_null_bytes(obj):
    """Recursively remove null bytes (\u0000) from strings in a parsed JSON object."""
    if isinstance(obj, str):
        return obj.replace('\x00', '')
    if isinstance(obj, dict):
        return {k: _sanitize_null_bytes(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize_null_bytes(i) for i in obj]
    return obj


def _safe_parse_json(text: str, context_name: str = "") -> dict:
    """
    Parse JSON with a 3-level fallback chain:
      1. json.loads(text)
      2. Clean markdown wrappers → retry json.loads
      3. json_repair.loads(text)  (if library available)
      4. Return error dict with raw excerpt
    """
    # Level 1: direct parse
    try:
        return _sanitize_null_bytes(json.loads(text))
    except json.JSONDecodeError:
        pass

    # Level 2: strip markdown code fences
    cleaned = text
    if "```json" in cleaned:
        cleaned = cleaned.split("```json", 1)[1].split("```", 1)[0].strip()
    elif "```" in cleaned:
        cleaned = cleaned.split("```", 1)[1].split("```", 1)[0].strip()

    # Remove control characters that break JSON
    cleaned = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', cleaned)

    try:
        return _sanitize_null_bytes(json.loads(cleaned))
    except json.JSONDecodeError:
        pass

    # Level 3: json_repair
    if HAS_JSON_REPAIR:
        try:
            repaired = json_repair.loads(cleaned)
            if isinstance(repaired, dict):
                logger.info("json_repaired_successfully", context=context_name)
                return _sanitize_null_bytes(repaired)
        except Exception:
            pass

    # Level 4: give up — return error with raw excerpt for debugging
    logger.warning("json_parse_failed_all_levels", context=context_name, raw_excerpt=text[:200])
    return {
        "error": f"JSON malformado para {context_name}",
        "raw_response": text[:500],
    }


def _calc_max_tokens(code_length: int) -> int:
    """Calculate dynamic max_tokens based on code size."""
    if code_length < 100:
        return 1024
    elif code_length <= 500:
        return 1536
    else:
        return 2048


async def bedrock_llm_call(prompt: str, function_name: str, max_tokens: int = 1024) -> dict:
    """
    Ejecuta una llamada asíncrona a Claude en AWS Bedrock
    usando asyncio.to_thread para no bloquear el Worker de FastAPI.
    Includes transparent caching when enabled.
    """
    # ── Cache check ───────────────────────────────────────────────
    from src.config import settings
    if settings.enable_llm_cache:
        cache = _get_cache()
        cached = cache.get(prompt)
        if cached and isinstance(cached, dict) and "error" not in cached:
            logger.debug("llm_cache_hit", function=function_name)
            return cached

    def _invoke():
        client = get_bedrock_client()
        payload = {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": max_tokens,
            "temperature": 0.1, 
            "messages": [
                {
                    "role": "user",
                    "content": prompt
                }
            ]
        }
        
        response = client.invoke_model(
            modelId=MODEL_ID,
            body=json.dumps(payload),
            contentType="application/json",
            accept="application/json"
        )
        body = json.loads(response['body'].read().decode('utf-8'))
        response_text = body['content'][0]['text']
        
        return _safe_parse_json(response_text, function_name)

    try:
        result = await asyncio.to_thread(_invoke)

        # ── Cache store ───────────────────────────────────────────
        if settings.enable_llm_cache:
            cache = _get_cache()
            cache.put(prompt, result)

        return result
    except Exception as e:
        logger.error("bedrock_call_failed", function=function_name, error=str(e))
        return None

async def analyze_functions_batch(funciones: List[Dict], max_concurrent: int = 5) -> List[Dict]:
    """
    Toma una lista de diccionarios de funciones y lanza el prompt para 
    cada uno de forma concurrente, devolviendo los resultados procesados.
    Usa un semáforo para controlar la concurrencia máxima.
    """
    semaphore = asyncio.Semaphore(max_concurrent)
    
    async def _limited_call(prompt, name, tokens=1024):
        async with semaphore:
            return await bedrock_llm_call(prompt, name, max_tokens=tokens)
    
    tareas = []
    
    for func in funciones:
        code = func.get('codigo_original', 'Sin código')
        code_lines = code.count('\n') + 1
        tokens = _calc_max_tokens(code_lines)
        prompt = PROMPT_TACTICO.format(
            nombre_funcion=func.get('nombre_funcion'),
            tipo_unidad=func.get('tipo_unidad', 'función'),
            esquema_clase=func.get('componente', 'Desconocido'),
            codigo_original=code
        )
        tareas.append(_limited_call(prompt, func.get('nombre_funcion'), tokens))
        
    logger.info("llm_batch_started", size=len(tareas))
    resultados_ia = await asyncio.gather(*tareas, return_exceptions=True)
    logger.info("llm_batch_completed")

    resultados_finales = []
    
    for idx, func in enumerate(funciones):
        res_ia = resultados_ia[idx]
        
        enriched = {
            "nombre_funcion": func.get('nombre_funcion'),
            "componente": func.get('componente'),
            "archivo": func.get('archivo'),
            "analisis_ia": {}
        }
        
        if isinstance(res_ia, Exception) or res_ia is None or (isinstance(res_ia, dict) and "error" in res_ia):
            enriched['analisis_ia'] = None
        else:
            enriched['analisis_ia'] = res_ia

        resultados_finales.append(enriched)

    return resultados_finales


async def analyze_files_batch(archivos: List[Dict], max_concurrent: int = 3) -> List[Dict]:
    """
    Toma una lista de diccionarios de archivos y lanza el PROMPT_ARCHIVO 
    para cada uno con concurrencia controlada.
    """
    semaphore = asyncio.Semaphore(max_concurrent)
    
    async def _limited_call(prompt, name):
        async with semaphore:
            return await bedrock_llm_call(prompt, name)
    
    tareas = []
    
    for archivo in archivos:
        code = archivo.get('codigo_completo', 'Sin código')
        code_lines = code.count('\n') + 1
        tokens = _calc_max_tokens(code_lines)
        prompt = PROMPT_ARCHIVO.format(
            nombre_archivo=archivo.get('nombre_archivo'),
            lenguaje=archivo.get('lenguaje', 'Desconocido'),
            capa=archivo.get('capa', 'Sin clasificar'),
            codigo_completo=code
        )
        tareas.append(_limited_call(prompt, archivo.get('nombre_archivo'), tokens))
        
    logger.info("llm_files_batch_started", size=len(tareas))
    resultados_ia = await asyncio.gather(*tareas, return_exceptions=True)
    logger.info("llm_files_batch_completed")

    resultados_finales = []
    
    for idx, archivo in enumerate(archivos):
        res_ia = resultados_ia[idx]
        
        enriched = {
            "nombre_archivo": archivo.get('nombre_archivo'),
            "ruta_archivo": archivo.get('ruta_archivo'),
            "analisis_ia": {}
        }
        
        if isinstance(res_ia, Exception) or res_ia is None or (isinstance(res_ia, dict) and "error" in res_ia):
            enriched['analisis_ia'] = None
        else:
            enriched['analisis_ia'] = res_ia

        resultados_finales.append(enriched)

    return resultados_finales


# ══════════════════════════════════════════════════════════════════════
# Pipeline V2 — Context-Enriched Prompts
# ══════════════════════════════════════════════════════════════════════

PROMPT_ARCHIVO_CON_CONTEXTO = """
Eres un Arquitecto de Software Experto. Tu tarea es analizar un archivo de código fuente con conocimiento del contexto arquitectónico del proyecto al que pertenece.

<contexto_proyecto>
{contexto_proyecto}
</contexto_proyecto>

Archivo: {nombre_archivo}
Lenguaje: {lenguaje}
Capa detectada: {capa}

<codigo_completo>
{codigo_completo}
</codigo_completo>

INSTRUCCIONES: Usando el contexto del proyecto (arquitectura, dependencias, módulo), analiza el archivo y devuelve EXACTAMENTE este formato JSON purista sin bloques de markdown:
{{
  "resumen_archivo": "descripción concisa en español del propósito general del archivo, considerando su rol dentro del módulo y la arquitectura",
  "responsabilidad_principal": "string corto: ej. Controlador REST, Servicio de negocio, Repositorio de datos, Modelo de dominio, Configuración, Utilidad",
  "dependencias_clave": ["lista de imports/dependencias críticas del archivo"],
  "patrones_detectados": ["ej. Singleton, Repository, Factory, Observer"],
  "relacion_con_vecinos": "descripción breve de cómo este archivo se relaciona con los archivos de los que depende y los que lo usan",
  "endpoints_expuestos": [
    {{
      "metodo": "GET/POST/PUT/DELETE",
      "ruta": "/api/ejemplo",
      "descripcion": "breve descripción"
    }}
  ],
  "observaciones": ["notas relevantes sobre calidad, seguridad o mejoras, considerando el contexto arquitectónico"]
}}
"""


async def analyze_files_batch_with_context(
    archivos: List[Dict],
    max_concurrent: int = 5,
) -> List[Dict]:
    """
    Enrichment with context — V2 of analyze_files_batch.

    Each dict in ``archivos`` should include a ``contexto_proyecto`` key
    with the human-readable context block built by worker_pool._build_context_block.
    """
    semaphore = asyncio.Semaphore(max_concurrent)

    async def _limited_call(prompt, name, tokens=1024):
        async with semaphore:
            return await bedrock_llm_call(prompt, name, max_tokens=tokens)

    tareas = []

    for archivo in archivos:
        # Use context-enriched prompt if context is available
        contexto = archivo.get("contexto_proyecto", "")
        code = archivo.get("codigo_completo", "Sin código")
        code_lines = code.count('\n') + 1
        tokens = _calc_max_tokens(code_lines)

        if contexto:
            prompt = PROMPT_ARCHIVO_CON_CONTEXTO.format(
                nombre_archivo=archivo.get("nombre_archivo"),
                lenguaje=archivo.get("lenguaje", "Desconocido"),
                capa=archivo.get("capa", "Sin clasificar"),
                codigo_completo=code,
                contexto_proyecto=contexto,
            )
        else:
            # Fallback to the original prompt without context
            prompt = PROMPT_ARCHIVO.format(
                nombre_archivo=archivo.get("nombre_archivo"),
                lenguaje=archivo.get("lenguaje", "Desconocido"),
                capa=archivo.get("capa", "Sin clasificar"),
                codigo_completo=code,
            )
        tareas.append(_limited_call(prompt, archivo.get("nombre_archivo"), tokens))

    logger.info("llm_files_context_batch_started", size=len(tareas))
    resultados_ia = await asyncio.gather(*tareas, return_exceptions=True)
    logger.info("llm_files_context_batch_completed")

    resultados_finales = []

    for idx, archivo in enumerate(archivos):
        res_ia = resultados_ia[idx]

        enriched = {
            "nombre_archivo": archivo.get("nombre_archivo"),
            "ruta_archivo": archivo.get("ruta_archivo"),
            "analisis_ia": {},
        }

        if isinstance(res_ia, Exception) or res_ia is None or (isinstance(res_ia, dict) and "error" in res_ia):
            enriched["analisis_ia"] = None
        else:
            enriched["analisis_ia"] = res_ia

        resultados_finales.append(enriched)

    return resultados_finales

