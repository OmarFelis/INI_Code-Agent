# Bugs y Mejoras — Code-Agent

Fecha: 2025-06  
Alcance: Revisión completa del código fuente en `src/` y contraste con el esquema de BD (infra.unidades_logicas, infra.archivos_fuente).

---

## 1. BUGS (errores concretos que causan comportamiento incorrecto)

---

### BUG-01 — Loop de persistencia de unidades mal anidado
**Archivo:** `src/core/analyzers/pipeline.py` (~línea 130)  
**Severidad:** Alta

El loop que persiste `unidades_logicas` está anidado dentro del loop de `archivos`, pero itera sobre **todas** las unidades en cada iteración de archivo. Resultado: cada unidad se intenta persistir N veces (donde N = número de archivos).

```python
# ACTUAL (incorrecto)
for archivo in archivos:
    resp = await aone_client.post_archivo_fuente(archivo)
    for unidad in unidades:          # ← itera TODAS las unidades
        if unidad.archivo_id == archivo.id and archivo_id:
            unidad.archivo_id = archivo_id
        if archivo_id:
            await aone_client.post_unidad_logica(unidad)  # ← se llama N veces por unidad

# CORRECTO
for archivo in archivos:
    resp = await aone_client.post_archivo_fuente(archivo)
    archivo_id = resp.get("id") or resp.get("data", {}).get("id")
    for unidad in [u for u in unidades if u.archivo_id == archivo.id]:
        if archivo_id:
            unidad.archivo_id = archivo_id
        await aone_client.post_unidad_logica(unidad)
```

---

### BUG-03 — Solo se guarda la última regla de negocio del loop
**Archivo:** `src/core/integration/aone_client.py` (~línea 155)  
**Severidad:** Alta

El loop que extrae `reglas_de_negocio` sobreescribe `desc` y `codigo` en cada iteración pero solo hace `append` **fuera** del loop. Solo se persiste la última regla de cada unidad.

```python
# ACTUAL (incorrecto)
for regla in ia_data["reglas_de_negocio"]:
    desc = regla.get("descripcion", "")
    codigo = regla.get("codigo_relacionado")
# append está FUERA del for ↑
reglas_negocio.append({...})

# CORRECTO
for regla in ia_data["reglas_de_negocio"]:
    desc = regla.get("descripcion", "") if isinstance(regla, dict) else str(regla)
    codigo = regla.get("codigo_relacionado") if isinstance(regla, dict) else None
    reglas_negocio.append({
        "id": str(uuid.uuid4()),
        "unidad_logica_id": u["id"],
        "descripcion": desc,
        "codigo_relacionado": codigo,
        ...
    })
```

---

### BUG-04 — Status `IN_PROGRESS` no existe en el modelo de dominio
**Archivo:** `src/api/routes/scan.py` (~línea 175) y `src/models/domain.py`  
**Severidad:** Media

El background task actualiza el job a `"IN_PROGRESS"`, pero el enum `ScanStatus` solo define: `QUEUED`, `RUNNING`, `COMPLETED`, `PARTIAL`, `FAILED`. El ORM acepta cualquier string (no hay validación), pero el estado queda inconsistente con el resto del sistema.

```python
# ACTUAL
await repository.update_scan_job_status(session, job_id, status="IN_PROGRESS")

# CORRECTO — usar el valor definido en el enum
await repository.update_scan_job_status(session, job_id, status="RUNNING")
```

---

### BUG-05 — `datetime.utcnow()` deprecado en Python 3.12+
**Archivo:** `src/db/repository.py` (~líneas 58, 61)  
**Severidad:** Media

`datetime.utcnow()` está deprecado desde Python 3.12 y será removido en versiones futuras. Produce un `DeprecationWarning` en runtime.

```python
# ACTUAL
values["started_at"] = datetime.utcnow()

# CORRECTO
from datetime import datetime, timezone
values["started_at"] = datetime.now(timezone.utc)
```

---

### BUG-06 — Asignación de `archivo` a unidades por conteo, no por FK real
**Archivo:** `src/api/routes/scan.py` (~línea 115)  
**Severidad:** Media

La función `_build_results` asigna el nombre de archivo a cada unidad contando `total_clases + total_funciones` por archivo. Si el extractor produce más o menos unidades que ese conteo (por clases anidadas, lambdas, etc.), las unidades quedan asignadas al archivo incorrecto.

```python
# ACTUAL — asignación por conteo secuencial (frágil)
for a_idx, archivo in enumerate(result.archivos):
    count = archivo.total_clases + archivo.total_funciones
    for i in range(count):
        if unidad_idx < len(unidades):
            unidades[unidad_idx]["archivo"] = archivo.nombre

# CORRECTO — usar el archivo_id que ya viene en la unidad
for u_dict, u_obj in zip(unidades, result.unidades):
    archivo_match = next((a for a in result.archivos if a.id == u_obj.archivo_id), None)
    u_dict["archivo"] = archivo_match.nombre if archivo_match else "unknown"
```

---

### BUG-07 — `escaneado_en` en `escaneo` usa `datetime.now()` sin timezone
**Archivo:** `src/api/routes/scan.py` (~línea 145)  
**Severidad:** Baja

En `_build_results`, el campo `escaneado_en` del escaneo usa `datetime.now().isoformat()` (naive, sin timezone), mientras que el resto del sistema usa `datetime.now(timezone.utc).isoformat()`.

```python
# ACTUAL
"escaneado_en": datetime.now().isoformat(),

# CORRECTO
"escaneado_en": datetime.now(timezone.utc).isoformat(),
```

---

### BUG-08 — Credenciales AWS hardcodeadas en el enricher
**Archivo:** `src/core/enricher/llm_enricher.py` (~líneas 32-34)  
**Severidad:** Alta (seguridad)

El `PROFILE_NAME` y `REGION` están hardcodeados en el módulo. Si el perfil no existe en el entorno de ejecución (Docker, CI/CD, Lambda), el cliente Bedrock falla con un error críptico. Además, expone el nombre de cuenta AWS en el código fuente.

```python
# ACTUAL
REGION = "us-east-1"
MODEL_ID = "anthropic.claude-3-haiku-20240307-v1:0"
PROFILE_NAME = "AmazonBedrockLimitedAccess-460896925620"

# CORRECTO — leer de settings/env
REGION = settings.aws_default_region
MODEL_ID = settings.bedrock_model_id  # agregar al Settings
PROFILE_NAME = settings.aws_profile   # ya existe en Settings, usarlo
```

---

### BUG-09 — `commit_hash` queda `null` en scans clonados desde repo remoto
**Archivo:** `src/core/analyzers/pipeline.py` (~línea 85) y `src/api/routes/scan.py` (~línea 195)  
**Severidad:** Media  
**Afectados:** 10 de 23 JSONs en `data/results/` tienen `commit_hash: null`

`_get_commit_hash` se ejecuta sobre `project_path` justo después del clone, antes de que el repo sea movido a `repos_cache`. Si el clone no completó el historial git en ese instante (shallow clone, timing, error silencioso), retorna `None`. Ese `null` queda grabado permanentemente en el JSON — el move posterior a `repos_cache` no lo corrige porque el pipeline ya terminó.

Además, en `_build_results` el `commit_hash` del escaneo se toma del primer archivo:
```python
"commit_hash": getattr(result.archivos[0], 'commit_hash', None) if result.archivos else None
```
Si el primer archivo tiene `null`, todo el escaneo queda sin hash aunque otros archivos sí lo tengan.

**Fix:** Ejecutar `_get_commit_hash` sobre la ruta final (después del move a cache), o como fallback re-intentarlo desde `repos_cache/{job_id}` al construir el resultado.

```python
# En _run_scan_background_task, después del move a cache:
if not any(a.commit_hash for a in result.archivos):
    from src.core.analyzers.pipeline import _get_commit_hash
    commit_hash = _get_commit_hash(final_project_path)
    for archivo in result.archivos:
        archivo.commit_hash = commit_hash
```

---

## 2. MEJORAS (no son bugs pero degradan calidad, mantenibilidad o seguridad)

---

### MEJ-01 — Duplicación de `AOneClient` en dos módulos distintos
**Archivos:** `src/integrations/aone_client.py` y `src/core/integration/aone_client.py`  
**Impacto:** Mantenibilidad

Existen dos clientes HTTP para A-ONE: `AOneClient` (integrations) y `AOneSyncClient` (core/integration). Tienen responsabilidades solapadas y se mantienen por separado. Cualquier cambio en la URL base o headers debe hacerse en dos lugares.

**Mejora:** Consolidar en un único cliente en `src/integrations/aone_client.py` con métodos tanto de escritura individual como de sync masivo.

---

### MEJ-02 — `_build_results` en `scan.py` es una función de 150+ líneas
**Archivo:** `src/api/routes/scan.py`  
**Impacto:** Mantenibilidad / Testabilidad

La función `_build_results` mezcla transformación de datos, cálculo de métricas y construcción del payload de respuesta. Es difícil de testear unitariamente y propensa a bugs (como BUG-06).

**Mejora:** Extraer a un módulo `src/core/serializers/result_serializer.py` con funciones pequeñas y testeables: `serialize_archivo()`, `serialize_unidad()`, `build_escaneo_summary()`.

---

### MEJ-03 — Background tasks de FastAPI no tienen manejo de timeout
**Archivo:** `src/api/routes/scan.py`, `scan_batch.py`  
**Impacto:** Resiliencia

Los background tasks (`_run_scan_background_task`, `_run_enrich_all_background_task`, etc.) no tienen timeout. Un scan de un repositorio grande o una llamada Bedrock colgada puede dejar el job en estado `RUNNING`/`IN_PROGRESS` indefinidamente.

**Mejora:** Agregar un timeout global con `asyncio.wait_for()` y actualizar el job a `FAILED` si se excede.

```python
try:
    await asyncio.wait_for(_run_pipeline(...), timeout=settings.scan_timeout_seconds)
except asyncio.TimeoutError:
    await repository.update_scan_job_status(session, job_id, status="FAILED",
        error_message="Scan timeout exceeded")
```

---

### MEJ-04 — No hay limpieza automática de `repos_cache`
**Archivo:** `src/config.py` (define `repos_cache_ttl_days`), ningún módulo lo implementa  
**Impacto:** Operacional (disco)

El setting `repos_cache_ttl_days = 7` existe pero no hay ningún proceso que lo aplique. Los repositorios clonados se acumulan indefinidamente en `repos_cache/`.

**Mejora:** Agregar una tarea de limpieza periódica (startup event o cron) que elimine directorios más antiguos que `repos_cache_ttl_days`.

---

### MEJ-05 — `aone_base_url` hardcodeada con URL de producción como default
**Archivo:** `src/config.py` (~línea 20)  
**Impacto:** Seguridad / Entornos

El default de `aone_base_url` apunta directamente a la URL Lambda de producción. Un desarrollador que levante el proyecto localmente sin `.env` enviará datos reales a producción sin saberlo.

**Mejora:** Cambiar el default a `""` o `"http://localhost:3000"` y hacer que la app falle explícitamente si no está configurada.

---

### MEJ-06 — `analisis_ia` en `archivos_fuente` se hace `pop()` y luego se re-asigna
**Archivo:** `src/core/integration/aone_client.py` (~línea 115)  
**Impacto:** Correctitud / Efectos secundarios

```python
ia = f.pop("analisis_ia", None)   # modifica el dict original del job
if ia is not None:
    f["analisis_ia"] = json.dumps(ia) if isinstance(ia, dict) else ia
```

Esto muta el dict `job.results` en memoria. Si `sync_scan_results` se llama dos veces (retry), el segundo intento encontrará `analisis_ia` ya serializado como string y lo volverá a serializar (`json.dumps` de un string), corrompiendo el dato.

**Mejora:** Trabajar sobre una copia del dict o serializar sin mutar el original.

---

### MEJ-07 — Falta campo `analisis_ia` en la respuesta JSON de `unidades_logicas`
**Archivo:** `src/api/routes/scan.py` (~línea 100)  
**Impacto:** Contrato de API / Consistencia con BD

En `_build_results`, el dict de cada unidad lógica no incluye `analisis_ia` (queda como `None` implícito). Sin embargo, la tabla `infra.unidades_logicas` (una vez agregada la columna, ver BUG-02) y el modelo `UnidadLogica` sí lo tienen. El campo solo se agrega después del enrich, pero no se inicializa en el scan inicial.

**Mejora:** Inicializar explícitamente `"analisis_ia": None` en el dict de cada unidad en `_build_results`.

---

### MEJ-08 — `_run_batch_background_task` carga todos los jobs en memoria antes de ejecutar
**Archivo:** `src/api/routes/scan_batch.py` (~línea 75)  
**Impacto:** Escalabilidad

El batch task abre una sesión, carga todos los jobs del batch en memoria, cierra la sesión, y luego ejecuta los scans secuencialmente. Si un scan falla y necesita actualizar el job, ya no tiene sesión activa (cada scan abre la suya propia vía `async_session_factory`). El diseño es correcto en ese sentido, pero la carga inicial es innecesaria si los jobs se pueden obtener por `batch_id` dentro de cada scan.

---

### MEJ-09 — `SKIP_FILES` en `project_analyzer.py` excluye `__init__.py` globalmente
**Archivo:** `src/core/analyzers/project_analyzer.py` (~línea 25)  
**Impacto:** Cobertura de análisis

`__init__.py` se excluye siempre, pero en proyectos donde `__init__.py` contiene lógica real (re-exports, configuración de módulo, factories), se pierde cobertura de análisis.

**Mejora:** Solo excluir `__init__.py` si está vacío o contiene únicamente imports.

---

### MEJ-10 — No hay validación de que `project_path` no escape del directorio base
**Archivo:** `src/api/routes/scan.py` (~línea 210)  
**Impacto:** Seguridad (Path Traversal)

La validación actual solo comprueba que el path exista y sea un directorio:
```python
if not request.repo_url and not os.path.isdir(request.project_path):
    raise HTTPException(...)
```

Un atacante con acceso al API podría pasar `project_path = "/"` o `"../../etc"` y escanear directorios arbitrarios del servidor.

**Mejora:** Validar que el path esté dentro de un directorio base permitido (whitelist).

```python
allowed_base = os.path.abspath(settings.repos_cache_dir)
requested = os.path.abspath(request.project_path)
if not requested.startswith(allowed_base):
    raise HTTPException(status_code=403, detail="project_path not allowed")
```

---

## 3. DEUDA TÉCNICA (schema / contrato JSON vs BD)

| # | Descripción | Impacto |
|---|---|---|
| DT-01 | Campo `resumen` en `infra.archivos_fuente` no se mapea desde `analisis_ia.resumen_archivo` en el sync | El campo queda siempre NULL |
| DT-03 | `parent` en JSON es string (nombre), BD espera `parent_id` (UUID) — el sync lo resuelve pero solo si la clase aparece antes que sus métodos en la lista | Métodos de clases definidas al final del archivo quedan sin `parent_id` |
| DT-04 | `escaneo_id` no se incluye en el JSON de respuesta del scan — se inyecta en el sync pero no queda en el resultado almacenado en `scan_jobs.results` | El JSON guardado en SQLite no es autosuficiente para re-sincronizar |
| DT-05 | `lineas_total` en el JSON del escaneo no tiene campo equivalente en `infra.escaneos` | Dato calculado se pierde |

---

## 4. RESUMEN PRIORIZADO

| Prioridad | ID | Descripción |
|---|---|---|
| 🔴 Crítico | BUG-01 | Loop de persistencia duplica unidades |
| 🔴 Crítico | BUG-03 | Solo se guarda la última regla de negocio |
| 🔴 Crítico | BUG-08 | Credenciales AWS hardcodeadas |
| 🟠 Alto | BUG-04 | Status `IN_PROGRESS` no definido en enum |
| 🟠 Alto | MEJ-10 | Path traversal en `project_path` |
| 🟡 Medio | BUG-09 | `commit_hash` null en 10/23 scans — se captura antes del move a cache |
| 🟡 Medio | BUG-05 | `datetime.utcnow()` deprecado |
| 🟡 Medio | BUG-06 | Asignación de archivo a unidades por conteo |
| 🟡 Medio | BUG-07 | `escaneado_en` sin timezone |
| 🟡 Medio | MEJ-01 | Duplicación de AOneClient |
| 🟡 Medio | MEJ-03 | Sin timeout en background tasks |
| 🟡 Medio | MEJ-06 | Mutación del dict en sync causa doble serialización |
| 🟢 Bajo | MEJ-02 | `_build_results` demasiado grande |
| 🟢 Bajo | MEJ-04 | Sin limpieza automática de repos_cache |
| 🟢 Bajo | MEJ-05 | URL de producción como default en config |
| 🟢 Bajo | MEJ-07 | `analisis_ia` no inicializado en scan inicial |
| 🟢 Bajo | MEJ-09 | `__init__.py` excluido globalmente |
| 🟡 Medio | DT-01 | `resumen` en `archivos_fuente` siempre NULL (no se mapea desde `analisis_ia`) |
| 🟠 Alto | DT-03 | `parent_id` no resuelto si la clase aparece después de sus métodos |
| 🟠 Alto | DT-04 | `escaneo_id` no queda en `scan_jobs.results` — JSON no autosuficiente para re-sync |
| 🟢 Bajo | DT-05 | `lineas_total` del escaneo no tiene columna en `infra.escaneos` — dato se pierde |
