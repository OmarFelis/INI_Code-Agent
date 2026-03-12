# Plan de Refactorización — Code-Agent V2.0
**Fecha:** 2026 | **Estado:** Propuesta para aprobación

---

## Diagnóstico: Por qué refactorizar

El sistema actual tiene 3 problemas estructurales que limitan su escalabilidad y mantenibilidad:

1. **Blob JSON gigante** — `scan_jobs.results` almacena todo el resultado como un JSON de varios MB. Un microservicio con 200 archivos y 2000 funciones genera ~5MB por scan. No es consultable, no es filtrable, y se lee completo en cada operación.

2. **Flujo partido en dos** — El usuario debe disparar `POST /scan` y luego `POST /scan/{id}/enrich-all` manualmente. Los datos en A-ONE quedan incompletos si se olvida el segundo paso.

3. **Triple transformación del mismo dato** — `PipelineResult` (Pydantic) → `_build_results()` (dict plano) → `AOneSyncClient` (dict para HTTP). Tres representaciones del mismo dato sin valor agregado, con bugs de mapeo entre ellas.

---

## Visión del Sistema Refactorizado

```
POST /scan
    │
    └─ [BACKGROUND] Pipeline Unificado
         │
         ├─ PASS 1: AST Extraction (paralelo)     → escribe a BD local directamente
         ├─ PASS 2: LLM Enrichment (paralelo)     → actualiza columnas en BD local
         ├─ PASS 3: Semgrep Security (opcional)   → actualiza escaneo.seguridad
         └─ PASS 4: A-ONE Sync                    → lee de BD local, sincroniza
```

Un solo disparo. Un solo flujo. Datos normalizados desde el primer momento.

---

## Arquitectura de Datos — 5 Tablas Locales

### Principios de diseño
- `activo_id` y `aplicacion_id` solo en `escaneos` — los hijos los heredan por JOIN
- `overall_score`, `risk_level`, `capa` son columnas directas en `unidades_logicas`
- `resumen` y `modifica_estado` son columnas directas — el LLM escribe ahí directamente
- `analisis_ia` desaparece como campo — sus partes van a columnas específicas
- JSONB solo para datos genuinamente semi-estructurados (`metricas`, `imports`, `compliance`)
- `reglas_negocio` es tabla real, no array dentro de metadata

### ERD

```
scan_jobs (1)
    └──── escaneos (1)
               └──── archivos_fuente (N)
                          └──── unidades_logicas (N)
                                     └──── reglas_negocio (N)
```

### Tabla: `scan_jobs`
> Solo tracking del job. Sin blob de resultados.

| Columna | Tipo | Descripción |
|---|---|---|
| `id` | UUID PK | ID del job |
| `status` | VARCHAR(20) | `QUEUED`, `RUNNING`, `COMPLETED`, `PARTIAL`, `FAILED` |
| `activo_id` | VARCHAR(36) | FK referencial a A-ONE |
| `aplicacion_id` | VARCHAR(36) | FK referencial a A-ONE |
| `microservice_name` | VARCHAR(255) | Nombre legible |
| `project_path` | TEXT | Ruta local o cache |
| `branch` | VARCHAR(100) | Rama analizada |
| `batch_id` | VARCHAR(36) | Agrupación de batch (nullable) |
| `escaneo_id` | UUID FK | → `escaneos.id` (se llena al completar) |
| `total_files` | INT | Total de archivos detectados |
| `processed_files` | INT | Archivos procesados exitosamente |
| `error_message` | TEXT | Error si FAILED |
| `created_at` | TIMESTAMP | |
| `started_at` | TIMESTAMP | |
| `completed_at` | TIMESTAMP | |

### Tabla: `escaneos`
> 1 fila por ejecución del pipeline. Métricas agregadas.

| Columna | Tipo | Descripción |
|---|---|---|
| `id` | UUID PK | |
| `job_id` | UUID FK | → `scan_jobs.id` |
| `activo_id` | VARCHAR(36) | Solo aquí — no se repite en hijos |
| `aplicacion_id` | VARCHAR(36) | Solo aquí — no se repite en hijos |
| `microservice_name` | VARCHAR(255) | |
| `commit_hash` | VARCHAR(40) | |
| `branch` | VARCHAR(100) | |
| `generado_por` | VARCHAR(100) | `"code-agent-v2.0"` |
| `score_general` | DECIMAL(5,2) | Promedio de scores de unidades |
| `nivel_riesgo` | VARCHAR(10) | `LOW`, `MEDIUM`, `HIGH` |
| `archivos_total` | INT | |
| `funciones_total` | INT | |
| `clases_total` | INT | |
| `lineas_total` | INT | |
| `metricas` | JSONB | `{avg_complexity, max_complexity, languages, risk_distribution}` |
| `arquitectura` | JSONB | `{capas: {Dominio: N, ...}, multi_layer_count: N}` |
| `seguridad` | JSONB | Resultados Semgrep — se llena en Pass 3 |
| `cumplimiento` | JSONB | `{loc_ok_pct, complexity_ok_pct, docstring_pct}` |
| `negocio` | JSONB | Resumen agregado de reglas (se llena en Pass 2) |
| `escaneado_en` | TIMESTAMP | |
| `created_at` | TIMESTAMP | |

### Tabla: `archivos_fuente`
> 1 fila por archivo analizado.

| Columna | Tipo | Descripción |
|---|---|---|
| `id` | UUID PK | Generado en Pass 1, estable |
| `escaneo_id` | UUID FK | → `escaneos.id` |
| `nombre` | VARCHAR(255) | |
| `ruta_archivo` | TEXT | Ruta relativa en el repo |
| `proposito` | VARCHAR(30) | `Controller`, `Service`, `Repository`, etc. |
| `capa` | VARCHAR(20) | `Dominio`, `Infraestructura`, `Adaptador` |
| `lenguaje` | VARCHAR(20) | `Python`, `Java`, `JavaScript`, `TypeScript` |
| `total_funciones` | INT | |
| `total_clases` | INT | |
| `endpoints` | INT | Conteo |
| `operaciones_bd` | INT | Conteo |
| `llamadas_externas` | INT | Conteo |
| `complejidad_ciclomatica` | INT | |
| `lineas_codigo` | INT | |
| `resumen` | TEXT | **Generado por LLM en Pass 2** — columna directa |
| `imports` | JSONB | Lista de imports del archivo |
| `metadata` | JSONB | `{decorators, api_endpoints_detail, db_calls_detail}` |
| `commit_hash` | VARCHAR(40) | |
| `escaneado_en` | TIMESTAMP | |

### Tabla: `unidades_logicas`
> 1 fila por clase o función.

| Columna | Tipo | Descripción |
|---|---|---|
| `id` | UUID PK | Generado en Pass 1, estable |
| `archivo_id` | UUID FK | → `archivos_fuente.id` — FK real, no nombre |
| `parent_id` | UUID FK | → `unidades_logicas.id` (self-ref, clase padre) |
| `nombre` | VARCHAR(255) | |
| `tipo` | VARCHAR(20) | `CLASE`, `FUNCION` |
| `linea_inicio` | INT | |
| `linea_fin` | INT | |
| `complejidad` | INT | |
| `lineas_codigo` | INT | |
| `accede_bd` | BOOLEAN | |
| `llamadas_externas` | INT | |
| `docstring` | BOOLEAN | |
| `capa` | VARCHAR(20) | **Columna directa** — no dentro de metadata |
| `overall_score` | DECIMAL(5,2) | **Columna directa** — no dentro de metadata |
| `risk_level` | VARCHAR(10) | **Columna directa** — no dentro de metadata |
| `resumen` | TEXT | **Generado por LLM en Pass 2** — columna directa |
| `modifica_estado` | BOOLEAN | **Generado por LLM en Pass 2** — columna directa |
| `compliance` | JSONB | `{loc_ok, complexity_ok, has_multi_layer_coupling}` |
| `escaneado_en` | TIMESTAMP | |

### Tabla: `reglas_negocio`
> 1 fila por regla extraída por LLM.

| Columna | Tipo | Descripción |
|---|---|---|
| `id` | UUID PK | |
| `unidad_logica_id` | UUID FK | → `unidades_logicas.id` |
| `descripcion` | TEXT | Explicación en español |
| `codigo_relacionado` | TEXT | Snippet de código |
| `creado_por_ia` | BOOLEAN | `true` = borrador IA, `false` = validado humano |
| `created_at` | TIMESTAMP | |

---

## Fases de Implementación

---

### FASE 1 — Normalización de la Base de Datos
**Objetivo:** Reemplazar el blob JSON por las 5 tablas relacionales. Sin cambiar el flujo todavía.

**Archivos a modificar:**
- `src/db/models.py` — agregar 4 modelos ORM nuevos, modificar `ScanJobORM`
- `src/db/repository.py` — agregar operaciones CRUD para las 4 tablas nuevas
- `src/db/session.py` — sin cambios

**Cambios en `models.py`:**
- Eliminar columna `results: JSON` de `ScanJobORM`
- Agregar columna `escaneo_id: UUID FK` a `ScanJobORM`
- Crear `EscaneoORM`, `ArchivoFuenteORM`, `UnidadLogicaORM`, `ReglaNegocioORM`
- En `UnidadLogicaORM`: `capa`, `overall_score`, `risk_level`, `resumen`, `modifica_estado` como columnas directas

**Cambios en `repository.py`:**
- Agregar `create_escaneo()`, `create_archivo_fuente()`, `create_unidad_logica()`, `create_regla_negocio()`
- Agregar `update_unidad_resumen()` — para que Pass 2 actualice solo las columnas LLM
- Agregar `get_escaneo_with_archivos()` — para el GET del job
- Agregar `list_unidades_by_archivo()` — para el GET paginado
- Modificar `update_scan_job_status()` — recibe `escaneo_id` en vez de `results`

**Criterio de aceptación:**
- `POST /scan` completa y los datos están en las 5 tablas, no en un blob
- `GET /scan/{job_id}` reconstruye la respuesta desde JOINs
- No hay columna `results` en `scan_jobs`

---

### FASE 2 — Pipeline Unificado (Scan + Enrich en un solo flujo)
**Objetivo:** Eliminar los endpoints `/enrich`, `/enrich-all`, `/enrich-files`. El enriquecimiento LLM ocurre automáticamente dentro del pipeline principal.

**El nuevo flujo del background task:**

```
_run_scan_background_task()
    │
    ├─ PASS 1: AST Extraction (paralelo, worker_pool)
    │       └─ Escribe archivos_fuente + unidades_logicas a BD local
    │          con IDs estables generados aquí
    │
    ├─ PASS 2: LLM Enrichment (paralelo, worker_pool)
    │       └─ Lee archivos del disco
    │          Llama Bedrock con contexto
    │          UPDATE unidades_logicas SET resumen=, modifica_estado=
    │          INSERT reglas_negocio
    │          UPDATE archivos_fuente SET resumen=
    │
    ├─ PASS 3: Semgrep Security (opcional)
    │       └─ UPDATE escaneos SET seguridad=
    │
    └─ PASS 4: A-ONE Sync
            └─ Lee de BD local (JOINs)
               Sincroniza a A-ONE via HTTP
               UPDATE scan_jobs SET status=COMPLETED, escaneo_id=
```

**Archivos a modificar:**
- `src/core/analyzers/pipeline.py` — agregar Pass 2 y Pass 3 dentro del pipeline, recibir `session` como parámetro
- `src/core/analyzers/worker_pool.py` — completar `run_parallel_enrichment()` (hoy solo construye payloads, no llama al LLM)
- `src/api/routes/scan.py` — eliminar `_build_results()`, eliminar los 3 endpoints de enrich, simplificar `_run_scan_background_task()`
- `src/api/routes/scan_batch.py` — sin cambios de lógica, solo adaptar al nuevo background task

**Cambios en `pipeline.py`:**
- Recibir `session: AsyncSession` como parámetro
- Pass 1: después de `worker_pool.run_parallel_extraction()`, hacer bulk insert a BD local con IDs generados aquí
- Pass 2: llamar `worker_pool.run_parallel_enrichment()` con los archivos del disco + contexto ya construido
  - El enrichment actualiza directamente las columnas `resumen`, `modifica_estado` en BD
  - Inserta `reglas_negocio` directamente
- Pass 3: si Semgrep habilitado, actualizar `escaneos.seguridad`
- Retornar `escaneo_id` en vez de `PipelineResult` con listas

**Cambios en `worker_pool.py`:**
- `run_parallel_enrichment()` debe leer el código del disco y llamar al LLM
- Recibir `project_path` y `session` para poder escribir directamente a BD
- Eliminar la reconstrucción artificial de contexto (`_rebuild_project_context`)

**Cambios en `scan.py`:**
- Eliminar `_build_results()` completamente
- Eliminar `_run_enrichment_background_task()`
- Eliminar `_run_enrich_all_background_task()`
- Eliminar `_run_enrich_files_background_task()`
- Eliminar `_rebuild_project_context()`
- Eliminar endpoints `/{job_id}/enrich`, `/{job_id}/enrich-all`, `/{job_id}/enrich-files`
- `_run_scan_background_task()` queda en ~40 líneas

**Criterio de aceptación:**
- `POST /scan` retorna job_id
- Al completar, `unidades_logicas.resumen` está poblado sin segundo disparo
- `reglas_negocio` tiene filas sin segundo disparo
- `scan.py` tiene menos de 150 líneas

---

### FASE 3 — API de Consulta Normalizada
**Objetivo:** Reemplazar el GET que devuelve el blob gigante por endpoints paginados y consultables.

**Nuevos endpoints:**

```
GET  /api/v1/scan/{job_id}
     → Resumen del escaneo (escaneo + métricas, sin archivos ni unidades)

GET  /api/v1/scan/{job_id}/archivos?page=1&limit=50&capa=Dominio
     → Lista paginada de archivos_fuente

GET  /api/v1/scan/{job_id}/archivos/{archivo_id}/unidades?tipo=FUNCION&risk=HIGH
     → Lista de unidades de un archivo, con filtros

GET  /api/v1/scan/{job_id}/unidades?risk=HIGH&capa=Dominio&page=1
     → Todas las unidades del scan con filtros (para dashboard)

GET  /api/v1/scan/{job_id}/reglas?page=1
     → Todas las reglas de negocio del scan
```

**Archivos a crear/modificar:**
- `src/api/routes/scan.py` — modificar `get_scan_result()`, agregar los nuevos endpoints
- `src/api/schemas/scan_response.py` — agregar schemas de respuesta paginada
- `src/db/repository.py` — agregar queries con filtros y paginación

**Cambios en `repository.py`:**
```python
# Nuevas funciones de consulta
async def get_escaneo_summary(session, job_id) -> EscaneoORM
async def list_archivos(session, escaneo_id, capa=None, page=1, limit=50)
async def list_unidades(session, escaneo_id, archivo_id=None, tipo=None, risk=None, page=1, limit=100)
async def list_reglas(session, escaneo_id, page=1, limit=100)
async def get_scan_stats(session, activo_id)  # histórico de scores
```

**Criterio de aceptación:**
- `GET /scan/{job_id}` devuelve solo el resumen (< 1KB)
- `GET /scan/{job_id}/unidades?risk=HIGH` devuelve solo las unidades de alto riesgo
- Respuestas paginadas con `total`, `page`, `limit`, `items`

---

### FASE 4 — A-ONE Sync Refactorizado
**Objetivo:** El `AOneSyncClient` lee de las tablas locales en vez de transformar un blob. IDs estables generados en Pass 1.

**Cambios en `src/core/integration/aone_client.py`:**
- `sync_scan_results()` recibe `escaneo_id: UUID` en vez de `job_results: dict`
- Lee los datos desde BD local con JOINs
- Los IDs de archivos y unidades ya existen (generados en Pass 1) — no se generan nuevos
- El mapeo `parent_id` es un UUID real desde BD — no hay resolución por nombre
- Serializar correctamente a TEXT los campos JSONB antes del POST (`json.dumps()`)
- Fix del bug de `reglas_negocio`: el loop de inserción estaba fuera del for

**Criterio de aceptación:**
- No hay `uuid.uuid4()` dentro de `sync_scan_results()`
- No hay duplicados en A-ONE al re-sincronizar el mismo scan
- `escaneos.seguridad` llega con datos de Semgrep (no `null`)

---

### FASE 5 — Limpieza y Calidad
**Objetivo:** Eliminar código muerto, corregir bugs menores, agregar limpieza automática de repos_cache.

**Cambios:**
- `src/api/main.py` — agregar tarea de limpieza de `repos_cache` en startup (archivos > `repos_cache_ttl_days`)
- `src/api/routes/scan.py` — corregir estado `IN_PROGRESS` → `RUNNING` (inconsistencia con el modelo)
- `src/api/main.py` — restringir CORS de `allow_origins=["*"]` a dominios configurados
- `src/core/integration/aone_client.py` — fix bug loop `reglas_negocio`
- `src/db/models.py` — agregar índices en `unidades_logicas(risk_level)`, `unidades_logicas(archivo_id)`, `archivos_fuente(escaneo_id)`
- Eliminar `src/integrations/aone_client.py` (duplicado de `src/core/integration/aone_client.py`)

---

## Resumen de Cambios por Archivo

| Archivo | Acción | Fase |
|---|---|---|
| `src/db/models.py` | Reemplazar blob por 4 modelos ORM nuevos | 1 |
| `src/db/repository.py` | Agregar CRUD + queries paginadas | 1, 3 |
| `src/core/analyzers/pipeline.py` | Integrar Pass 2 (LLM) y Pass 3 (Semgrep), recibir session | 2 |
| `src/core/analyzers/worker_pool.py` | Completar `run_parallel_enrichment()` con escritura a BD | 2 |
| `src/api/routes/scan.py` | Eliminar `_build_results()` y 3 endpoints enrich, simplificar | 2, 3 |
| `src/api/routes/scan_batch.py` | Adaptar al nuevo background task | 2 |
| `src/core/integration/aone_client.py` | Leer de BD local, IDs estables, fix bugs | 4 |
| `src/api/schemas/scan_response.py` | Agregar schemas paginados | 3 |
| `src/api/main.py` | CORS restringido, limpieza repos_cache en startup | 5 |
| `src/integrations/aone_client.py` | Eliminar (duplicado) | 5 |

---

## Impacto en la Experiencia del Flujo

### Antes
```
Usuario:
  1. POST /scan                    → espera ~30s
  2. POST /scan/{id}/enrich-all    → espera ~2min (manual, olvidable)
  3. GET  /scan/{id}               → recibe blob de 5MB
  4. Filtra manualmente en el JSON
```

### Después
```
Usuario:
  1. POST /scan                    → espera ~2.5min (todo incluido)
  2. GET  /scan/{id}               → recibe resumen < 1KB
  3. GET  /scan/{id}/unidades?risk=HIGH&capa=Dominio  → solo lo que necesita
```

---

## Orden de Ejecución Recomendado

```
FASE 1 (BD)  →  FASE 2 (Pipeline)  →  FASE 4 (Sync)  →  FASE 3 (API)  →  FASE 5 (Limpieza)
```

Fase 1 primero porque todas las demás dependen del nuevo esquema de BD.
Fase 4 antes que Fase 3 porque el sync debe funcionar antes de exponer los nuevos endpoints.

---

*Code-Agent V2.0 — Plan de Refactorización — Para aprobación del equipo*
