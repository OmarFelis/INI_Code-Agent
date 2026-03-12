# Plan de Refactorización V3.1 — Code-Agent
## "The Resilient Agent"

**Estado:** Propuesta actualizada — Aprobable para implementación controlada  
**Fecha:** 2026-03-12 (V3.1) | 2026-03-11 (V3.0 original)  
**Origen:** Evolución del Plan V2 + Respuestas a revisión técnica del comité  
**Versión:** 3.1

> [!IMPORTANT]
> **V3.1** incorpora las respuestas a las **10 observaciones** del comité de revisión técnica (ver [Anexo A — Sección 21](#21-anexo-a--respuestas-a-las-10-observaciones-del-comité-v31)). Las secciones 1–20 se mantienen intactas del V3.0 como cuerpo principal del plan.

---

## 1. Objetivo

Reestructurar el sistema de análisis de código Code-Agent para lograr:

- **Escalabilidad**: pipeline desacoplado por etapas, workers independientes
- **Resiliencia**: reintentos parciales sin reprocesar etapas exitosas
- **Idempotencia**: IDs determinísticos, upserts, constraints únicos
- **Observabilidad**: métricas, logs estructurados, tracing por etapa
- **Migración segura**: patrón Expand → Validate → Cutover → Contract

---

## 2. Diagnóstico del Sistema Actual

El diagnóstico del Plan V2 sigue siendo correcto. Se resumen los 3 problemas fundamentales:

### Problema 1 — Blob JSON gigante

`scan_jobs.results` almacena todo como un JSON de ~5 MB por microservicio. No es consultable ni filtrable.

**Estado actual del código:**
- [models.py](file:///c:/INI_Code-Agent/src/db/models.py): `results: Mapped[dict | None] = mapped_column(JSON, nullable=True)` (línea 38)
- [repository.py](file:///c:/INI_Code-Agent/src/db/repository.py): `update_scan_job_status()` acepta `results: dict | None` y lo guarda completo (línea 57-79)

### Problema 2 — Flujo partido en dos pasos manuales

El usuario debe disparar `POST /scan` y luego `POST /scan/{id}/enrich-all` manualmente.

**Estado actual del código:**
- [scan.py](file:///c:/INI_Code-Agent/src/api/routes/scan.py): 3 endpoints de enrich separados (`/enrich`, `/enrich-all`, `/enrich-files`) con ~400 líneas de código duplicado (líneas 410-783)

### Problema 3 — Triple transformación del mismo dato

`PipelineResult` → `_build_results()` → `AOneSyncClient` genera 3 representaciones del mismo dato.

**Estado actual del código:**
- [scan.py](file:///c:/INI_Code-Agent/src/api/routes/scan.py): `_build_results()` con 134 líneas de mapeo manual (líneas 53-186)
- [aone_client.py](file:///c:/INI_Code-Agent/src/core/integration/aone_client.py): `sync_scan_results()` genera `uuid.uuid4()` en cada sync (líneas 92, 118, 137, 179), causando duplicados

### Problema 4 — Sin resiliencia parcial (NUEVO en V3)

Si falla el enriquecimiento LLM, se pierde toda la extracción AST. Si falla el sync, se repite el LLM.

**Estado actual del código:**
- [pipeline.py](file:///c:/INI_Code-Agent/src/core/analyzers/pipeline.py): un solo flujo monolítico (277 líneas), sin checkpointing por etapa
- [scan.py](file:///c:/INI_Code-Agent/src/api/routes/scan.py): `_run_scan_background_task()` no persiste progreso intermedio

### Problema 5 — Sin observabilidad operativa (NUEVO en V3)

- [main.py](file:///c:/INI_Code-Agent/src/api/main.py): CORS con `allow_origins=["*"]` (línea 62)
- [config.py](file:///c:/INI_Code-Agent/src/config.py): feature flags parciales, sin métricas ni tracing

---

## 3. Qué se conserva del Plan V2

> [!NOTE]
> Estas decisiones del Plan V2 son correctas y se mantienen intactas:

| Decisión V2 | Estado en V3 |
|---|---|
| Sacar `results` como modelo principal de consulta | ✅ Se mantiene |
| Mover la consulta a endpoints paginados | ✅ Se mantiene |
| Eliminar la triple transformación de datos | ✅ Se mantiene |
| A-ONE lee de modelo consistente, no de blob | ✅ Se mantiene |
| `risk_level`, `overall_score`, `capa`, `resumen`, `modifica_estado` como columnas | ✅ Se mantiene |
| `reglas_negocio` como tabla real | ✅ Se mantiene |
| ERD: `scan_jobs → escaneos → archivos_fuente → unidades_logicas → reglas_negocio` | ✅ Se mantiene |

---

## 4. Qué cambia respecto al Plan V2

> [!IMPORTANT]
> Lo que **NO** se conserva es la idea de que todo se pueda meter de forma segura en un solo background task con un status general y sin estrategia de transición.

| Aspecto | Plan V2 | Plan V3 |
|---|---|---|
| Blob `results` | Se elimina de golpe | Coexiste temporalmente (doble escritura) |
| Pipeline | Un solo background task | Etapas persistidas y reintentables |
| Estado del job | `scan_jobs.status` general | `scan_stages` por etapa |
| Auditoría LLM | No existe | Tabla `llm_runs` |
| Hallazgos Semgrep | JSON agregado en `escaneos.seguridad` | Tabla `security_findings` atómica |
| Sync A-ONE | `uuid.uuid4()` en cada envío | IDs determinísticos + `sync_attempts` |
| API | Se cambia de golpe | V1 coexiste con V2 |
| Feature flags | Parciales | Completos para cada etapa |
| Observabilidad | No definida | Métricas, logs, tracing |
| Orden de rollout | `BD → Pipeline → Sync → API → Limpieza` | 8 fases con Expand/Contract |

---

## 5. Principios de Arquitectura V3

### 5.1 Persistencia Normalizada
Eliminar el blob como modelo principal. Modelo relacional jerárquico:
```
scan_jobs (1)
  └── escaneos (1)
        └── archivos_fuente (N)
              └── unidades_logicas (N)
                    └── reglas_negocio (N)
```

### 5.2 Pipeline por Etapas Persistidas
Cada etapa (EXTRACT, ENRICH, SECURITY, SYNC) es independiente, persistida y reintentable.

### 5.3 API Liviana
El endpoint solo crea el job, encola el trabajo y responde con `job_id`. No ejecuta trabajo pesado.

### 5.4 Workers Desacoplados
El procesamiento ocurre en workers separados del proceso API, con escalabilidad horizontal.

### 5.5 Idempotencia Completa
Todas las etapas pueden ejecutarse múltiples veces sin duplicar datos.

---

## 6. Arquitectura Lógica del Sistema

```
                              ┌─────────────┐
                              │   Client     │
                              └──────┬───────┘
                                     │
                              ┌──────▼───────┐
                              │   API (FastAPI) │
                              │   - POST /scan  │
                              │   - GET /scan/* │
                              └──────┬───────┘
                                     │
                      ┌──────────────┼──────────────┐
                      │              │              │
               ┌──────▼──────┐  ┌───▼────┐  ┌──────▼──────┐
               │ scan_jobs   │  │ scan_  │  │ Queue:      │
               │ (tracking)  │  │ stages │  │ scan.extract│
               └─────────────┘  └────────┘  └──────┬──────┘
                                                    │
                                             ┌──────▼──────┐
                                             │ Extract     │
                                             │ Worker      │
                                             │ (AST)       │
                                             └──────┬──────┘
                                                    │
                                    ┌───────────────┼───────────────┐
                                    │               │               │
                             ┌──────▼──────┐ ┌──────▼──────┐ ┌──────▼──────┐
                             │ archivos_   │ │ unidades_   │ │ Queue:      │
                             │ fuente      │ │ logicas     │ │ scan.enrich │
                             └─────────────┘ └─────────────┘ └──────┬──────┘
                                                                    │
                                                             ┌──────▼──────┐
                                                             │ Enrich      │
                                                             │ Worker      │
                                                             │ (LLM)       │
                                                             └──────┬──────┘
                                                                    │
                                                    ┌───────────────┼───────────┐
                                                    │               │           │
                                             ┌──────▼──────┐ ┌─────▼─────┐ ┌───▼───────┐
                                             │ reglas_     │ │ llm_runs  │ │ Queue:    │
                                             │ negocio     │ │ (audit)   │ │ scan.     │
                                             └─────────────┘ └───────────┘ │ security  │
                                                                           └───┬───────┘
                                                                               │
                                                                        ┌──────▼──────┐
                                                                        │ Security    │
                                                                        │ Worker      │
                                                                        │ (Semgrep)   │
                                                                        └──────┬──────┘
                                                                               │
                                                           ┌───────────────────┼──────────┐
                                                           │                   │          │
                                                    ┌──────▼──────┐   ┌────────▼────┐ ┌──▼─────────┐
                                                    │ security_   │   │ Queue:      │ │ escaneos   │
                                                    │ findings    │   │ scan.sync   │ │ .seguridad │
                                                    └─────────────┘   └──────┬──────┘ └────────────┘
                                                                             │
                                                                      ┌──────▼──────┐
                                                                      │ Sync Worker │
                                                                      │ (A-ONE)     │
                                                                      └──────┬──────┘
                                                                             │
                                                              ┌──────────────┼──────────┐
                                                              │              │          │
                                                       ┌──────▼──────┐ ┌─────▼─────┐  ┌▼──────────┐
                                                       │ A-ONE DB    │ │ sync_     │  │ scan_jobs │
                                                       │ (externo)   │ │ attempts  │  │ COMPLETED │
                                                       └─────────────┘ └───────────┘  └───────────┘
```

---

## 7. Modelo de Datos Final

### 7.1 Tablas del Plan V2 (se mantienen)

#### `scan_jobs`
> Solo tracking del job. Sin blob de resultados (eventualmente).

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
| `results` | JSON | **TEMPORAL — se mantiene durante doble escritura** |
| `created_at` | TIMESTAMP | |
| `started_at` | TIMESTAMP | |
| `completed_at` | TIMESTAMP | |

> [!WARNING]
> La columna `results` se mantiene temporalmente durante la Fase 2 (doble escritura). Se elimina en la Fase 7 (Contract) **solo después** de validar paridad completa.

#### `escaneos`
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
| `generado_por` | VARCHAR(100) | `"code-agent-v3.0"` |
| `score_general` | DECIMAL(5,2) | |
| `nivel_riesgo` | VARCHAR(10) | |
| `archivos_total` | INT | |
| `funciones_total` | INT | |
| `clases_total` | INT | |
| `lineas_total` | INT | |
| `metricas` | JSONB | `{avg_complexity, max_complexity, languages, risk_distribution}` |
| `arquitectura` | JSONB | `{capas: {Dominio: N, ...}, multi_layer_count: N}` |
| `seguridad` | JSONB | Resumen agregado Semgrep |
| `cumplimiento` | JSONB | `{loc_ok_pct, complexity_ok_pct, docstring_pct}` |
| `negocio` | JSONB | Resumen agregado de reglas |
| `escaneado_en` | TIMESTAMP | |
| `created_at` | TIMESTAMP | |

#### `archivos_fuente`
> 1 fila por archivo analizado.

| Columna | Tipo | Descripción |
|---|---|---|
| `id` | UUID PK | **Determinístico** (ver sección 8) |
| `escaneo_id` | UUID FK | → `escaneos.id` |
| `nombre` | VARCHAR(255) | |
| `ruta_archivo` | TEXT | Ruta relativa en el repo |
| `proposito` | VARCHAR(30) | Controller, Service, Repository, etc. |
| `capa` | VARCHAR(20) | Dominio, Infraestructura, Adaptador |
| `lenguaje` | VARCHAR(20) | Python, Java, JavaScript, TypeScript |
| `total_funciones` | INT | |
| `total_clases` | INT | |
| `endpoints` | INT | |
| `operaciones_bd` | INT | |
| `llamadas_externas` | INT | |
| `complejidad_ciclomatica` | INT | |
| `lineas_codigo` | INT | |
| `resumen` | TEXT | **Generado por LLM en Enrich** |
| `imports` | JSONB | Lista de imports |
| `metadata` | JSONB | `{decorators, api_endpoints_detail, db_calls_detail}` |
| `content_hash` | VARCHAR(64) | **NUEVO** — SHA-256 del contenido del archivo |
| `commit_hash` | VARCHAR(40) | |
| `escaneado_en` | TIMESTAMP | |

#### `unidades_logicas`
> 1 fila por clase o función.

| Columna | Tipo | Descripción |
|---|---|---|
| `id` | UUID PK | **Determinístico** (ver sección 8) |
| `archivo_id` | UUID FK | → `archivos_fuente.id` |
| `parent_id` | UUID FK | → `unidades_logicas.id` (self-ref) |
| `nombre` | VARCHAR(255) | |
| `tipo` | VARCHAR(20) | `CLASE`, `FUNCION` |
| `linea_inicio` | INT | |
| `linea_fin` | INT | |
| `complejidad` | INT | |
| `lineas_codigo` | INT | |
| `accede_bd` | BOOLEAN | |
| `llamadas_externas` | INT | |
| `docstring` | BOOLEAN | |
| `capa` | VARCHAR(20) | **Columna directa** |
| `overall_score` | DECIMAL(5,2) | **Columna directa** |
| `risk_level` | VARCHAR(10) | **Columna directa** |
| `resumen` | TEXT | **Generado por LLM en Enrich** |
| `modifica_estado` | BOOLEAN | **Generado por LLM en Enrich** |
| `compliance` | JSONB | `{loc_ok, complexity_ok, has_multi_layer_coupling}` |
| `content_hash` | VARCHAR(64) | **NUEVO** — SHA-256 del código de la unidad |
| `escaneado_en` | TIMESTAMP | |

#### `reglas_negocio`
> 1 fila por regla extraída por LLM.

| Columna | Tipo | Descripción |
|---|---|---|
| `id` | UUID PK | |
| `unidad_logica_id` | UUID FK | → `unidades_logicas.id` |
| `descripcion` | TEXT | Explicación en español |
| `codigo_relacionado` | TEXT | Snippet de código |
| `creado_por_ia` | BOOLEAN | |
| `created_at` | TIMESTAMP | |

---

### 7.2 Tablas NUEVAS para operación (añadidas en V3)

#### `scan_stages`
> Tracking de estado por etapa del pipeline. Reemplaza el tracking general por uno granular.

| Columna | Tipo | Descripción |
|---|---|---|
| `id` | UUID PK | |
| `job_id` | UUID FK | → `scan_jobs.id` |
| `stage_name` | VARCHAR(20) | `EXTRACT`, `ENRICH`, `SECURITY`, `SYNC` |
| `status` | VARCHAR(20) | `QUEUED`, `RUNNING`, `SUCCEEDED`, `FAILED`, `PARTIAL` |
| `attempt` | INT | Número de intento (comienza en 1) |
| `started_at` | TIMESTAMP | |
| `completed_at` | TIMESTAMP | |
| `error_code` | VARCHAR(50) | Código de error clasificado |
| `error_message` | TEXT | Detalle del error |
| `worker_id` | VARCHAR(100) | Identificador del worker que ejecutó |

**Constraint:** `UNIQUE(job_id, stage_name, attempt)`

#### `llm_runs`
> Auditoría completa de cada llamada al LLM. Esencial para control de costos y reproducibilidad.

| Columna | Tipo | Descripción |
|---|---|---|
| `id` | UUID PK | |
| `job_id` | UUID FK | → `scan_jobs.id` |
| `unidad_logica_id` | UUID FK nullable | → `unidades_logicas.id` |
| `archivo_id` | UUID FK nullable | → `archivos_fuente.id` |
| `model_name` | VARCHAR(100) | Ej: `anthropic.claude-3-sonnet` |
| `prompt_version` | VARCHAR(20) | Versión del prompt utilizado |
| `input_hash` | VARCHAR(64) | SHA-256 del input enviado |
| `output_hash` | VARCHAR(64) | SHA-256 del output recibido |
| `raw_output` | TEXT | Respuesta cruda del LLM (o `raw_output_s3_uri` si se mueve a S3) |
| `confidence_score` | DECIMAL(3,2) | Score de confianza del LLM (0.00–1.00) |
| `tokens_input` | INT | Tokens de entrada consumidos |
| `tokens_output` | INT | Tokens de salida consumidos |
| `latency_ms` | INT | Latencia de la llamada en ms |
| `created_at` | TIMESTAMP | |

#### `security_findings`
> Hallazgos atómicos de Semgrep. No agrupar todo en un JSON.

| Columna | Tipo | Descripción |
|---|---|---|
| `id` | UUID PK | |
| `job_id` | UUID FK | → `scan_jobs.id` |
| `archivo_id` | UUID FK | → `archivos_fuente.id` |
| `unidad_logica_id` | UUID FK nullable | → `unidades_logicas.id` |
| `rule_id` | VARCHAR(200) | ID de la regla Semgrep |
| `severity` | VARCHAR(20) | `ERROR`, `WARNING`, `INFO` |
| `message` | TEXT | Descripción del hallazgo |
| `line` | INT | Línea del hallazgo |
| `column` | INT | Columna |
| `fingerprint` | VARCHAR(64) | Hash para deduplicación |
| `created_at` | TIMESTAMP | |

**Constraint:** `UNIQUE(job_id, fingerprint)`

#### `sync_attempts`
> Trazabilidad real de cada intento de sincronización a A-ONE.

| Columna | Tipo | Descripción |
|---|---|---|
| `id` | UUID PK | |
| `job_id` | UUID FK | → `scan_jobs.id` |
| `escaneo_id` | UUID FK | → `escaneos.id` |
| `target_system` | VARCHAR(50) | `A-ONE` |
| `idempotency_key` | VARCHAR(128) | Clave única para deduplicación |
| `attempt` | INT | Número de intento |
| `request_hash` | VARCHAR(64) | SHA-256 del payload enviado |
| `response_code` | INT | HTTP status code |
| `response_body` | TEXT | Cuerpo de la respuesta (truncado) |
| `status` | VARCHAR(20) | `SENT`, `SUCCESS`, `FAILED`, `RETRYING` |
| `created_at` | TIMESTAMP | |

**Constraint:** `UNIQUE(target_system, idempotency_key)`

---

## 8. Reglas de Idempotencia

### 8.1 IDs Determinísticos

**Para archivo:**
```python
archivo_id = sha256(f"{repo_url}|{branch}|{commit_hash}|{ruta_archivo}")
```

**Para unidad lógica:**
```python
unidad_id = sha256(f"{repo_url}|{branch}|{commit_hash}|{ruta_archivo}|{nombre}|{tipo}|{firma}")
```

> [!CAUTION]
> No usar `linea_inicio` como parte de la identidad primaria si la entidad puede moverse al agregar código arriba.

### 8.2 Constraints Únicos

```sql
-- archivos_fuente
UNIQUE(escaneo_id, ruta_archivo)

-- unidades_logicas
UNIQUE(archivo_id, nombre, tipo, linea_inicio, linea_fin)

-- reglas_negocio
UNIQUE(unidad_logica_id, descripcion_hash)

-- scan_stages
UNIQUE(job_id, stage_name, attempt)

-- sync_attempts
UNIQUE(target_system, idempotency_key)

-- security_findings
UNIQUE(job_id, fingerprint)
```

### 8.3 Escrituras

**Siempre upsert, nunca inserts ciegos.** Ejemplo con SQLAlchemy:

```python
from sqlalchemy.dialects.postgresql import insert

stmt = insert(ArchivoFuenteORM).values(data)
stmt = stmt.on_conflict_do_update(
    index_elements=["escaneo_id", "ruta_archivo"],
    set_={col: stmt.excluded[col] for col in update_cols}
)
await session.execute(stmt)
```

---

## 9. Pipeline V3 — Etapas Persistidas

### 9.1 Stage: EXTRACT

| Aspecto | Detalle |
|---|---|
| **Entrada** | `project_path`, `commit_hash` |
| **Acciones** | Clonar/usar repo cache → Parsear AST → Generar IDs determinísticos |
| **Escritura** | INSERT `escaneos`, `archivos_fuente`, `unidades_logicas` |
| **Marca** | `scan_stages(EXTRACT) = SUCCEEDED` |
| **Reintento** | Seguro: upsert por IDs determinísticos |

### 9.2 Stage: ENRICH (LLM)

| Aspecto | Detalle |
|---|---|
| **Entrada** | Unidades pendientes de enriquecimiento |
| **Acciones** | Leer código → Enviar contexto a LLM → Guardar columnas derivadas |
| **Escritura** | UPDATE `unidades_logicas(resumen, modifica_estado, overall_score)` + INSERT `reglas_negocio` + INSERT `llm_runs` |
| **Marca** | `scan_stages(ENRICH) = SUCCEEDED` |
| **Optimización** | Si `content_hash` no cambió desde último scan, reusar resultado anterior (cache por hash) |
| **Reintento** | Seguro: solo actualiza columnas derivadas |

### 9.3 Stage: SECURITY (Semgrep)

| Aspecto | Detalle |
|---|---|
| **Entrada** | `project_path` |
| **Acciones** | Ejecutar Semgrep → Registrar findings atómicos → Componer resumen agregado |
| **Escritura** | INSERT `security_findings` + UPDATE `escaneos.seguridad` (resumen) |
| **Marca** | `scan_stages(SECURITY) = SUCCEEDED` |
| **Reintento** | Seguro: upsert por fingerprint |

### 9.4 Stage: SYNC (A-ONE)

| Aspecto | Detalle |
|---|---|
| **Entrada** | Modelo consolidado desde BD local |
| **Acciones** | Generar payload determinístico → Usar idempotency key → Enviar a A-ONE |
| **Escritura** | INSERT `sync_attempts` con request/response |
| **Marca** | `scan_stages(SYNC) = SUCCEEDED` |
| **Reintento** | Seguro: idempotency key previene duplicados |

### Beneficio clave

```
Si falla ENRICH → no se repite EXTRACT
Si falla SYNC   → no se repite LLM
Si falla SECURITY → no se afecta ENRICH ni EXTRACT
```

**Esto es lo que le faltaba al Plan V2.**

---

## 10. Scoring Determinístico (Fórmula)

> [!TIP]
> No dejar que el LLM invente el score. Calcularlo de forma determinista en EXTRACT y que el LLM solo aporte el "resumen".

**Fórmula propuesta para `overall_score`:**

```python
score = 100
score -= complejidad_ciclomatica * 2      # Penalizar complejidad
score -= riesgos_seguridad * 10            # Penalizar findings de seguridad
score += 5 if has_docstring else 0         # Premiar documentación
score -= 3 if lineas_codigo > 100 else 0   # Penalizar funciones largas
score -= 5 if accede_bd and llamadas_externas > 0 else 0  # Penalizar acoplamiento

overall_score = max(0, min(100, score))
```

**`risk_level` derivado:**
```python
if overall_score < 50 or complejidad > 15:
    risk_level = "HIGH"
elif overall_score < 70 or complejidad >= 10:
    risk_level = "MEDIUM"
else:
    risk_level = "LOW"
```

---

## 11. Compatibilidad API — Transición V1 → V2

### Estrategia

1. Mantener `GET /api/v1/scan/{job_id}` actual durante transición
2. Crear `GET /api/v2/scan/{job_id}` con resumen liviano
3. Hacer shadow comparison entre V1 y V2
4. Apagar V1 cuando ya no existan consumidores

### Endpoints V2

| Método | Endpoint | Descripción |
|---|---|---|
| `POST` | `/api/v2/scan` | Crear scan (devuelve `job_id`) |
| `GET` | `/api/v2/scan/{job_id}` | Resumen liviano (<1KB) |
| `GET` | `/api/v2/scan/{job_id}/stages` | Estado por etapa |
| `GET` | `/api/v2/scan/{job_id}/archivos` | Archivos paginados |
| `GET` | `/api/v2/scan/{job_id}/unidades` | Unidades con filtros (`?risk=HIGH&capa=Dominio`) |
| `GET` | `/api/v2/scan/{job_id}/reglas` | Reglas de negocio paginadas |
| `GET` | `/api/v2/scan/{job_id}/security-findings` | Hallazgos de seguridad |
| `POST` | `/api/v2/scan/{job_id}/retry-stage/{stage}` | Reintentar una etapa específica |
| `POST` | `/api/v2/scan/{job_id}/retry-sync` | Reintentar sync a A-ONE |

> Esto hace al sistema **operable**, no solo consultable.

---

## 12. Fases de Implementación (Rollout V3)

### Fase 0 — Hardening Previo (Baseline)

> Antes de tocar el flujo actual.

| Tarea | Detalle |
|---|---|
| Congelar contrato actual de `/scan` | Documentar request/response exacto |
| Inventariar consumidores del blob | ¿Quién lee `scan_jobs.results`? |
| Medir volumen real | scans/día, archivos/scan, funciones/scan, costo LLM/scan |
| Definir SLO mínimo | Latencia máxima, uptime objetivo |
| Agregar métricas básicas | `scan_duration`, `scan_count`, `error_rate` |

**Entregables:** Mapa de dependencias, baseline de latencia/costo, checklist de rollback.

---

### Fase 1 — Expand Schema

> Crear tablas nuevas **sin eliminar** `results`.

**Archivos a modificar:**

| Archivo | Cambio |
|---|---|
| [models.py](file:///c:/INI_Code-Agent/src/db/models.py) | Agregar 9 modelos ORM nuevos, **mantener** `results` en `ScanJobORM` |
| [repository.py](file:///c:/INI_Code-Agent/src/db/repository.py) | Agregar CRUD para las tablas nuevas con upsert |
| Migración Alembic (nuevo) | Script de migración para crear las tablas |

**Modelos ORM nuevos:**
1. `EscaneoORM`
2. `ArchivoFuenteORM`
3. `UnidadLogicaORM`
4. `ReglaNegocioORM`
5. `ScanStageORM`
6. `LlmRunORM`
7. `SecurityFindingORM`
8. `SyncAttemptORM`

**Criterio de aceptación:** Las tablas existen en PostgreSQL con constraints únicos. El sistema actual sigue funcionando sin cambios.

---

### Fase 2 — Doble Escritura

> El sistema genera el blob JSON **y además** pobla el modelo normalizado.

**Archivos a modificar:**

| Archivo | Cambio |
|---|---|
| [pipeline.py](file:///c:/INI_Code-Agent/src/core/analyzers/pipeline.py) | Recibir `session`, escribir a tablas normalizadas con IDs determinísticos |
| [scan.py](file:///c:/INI_Code-Agent/src/api/routes/scan.py) | `_run_scan_background_task()` escribe a AMBOS destinos |

**Criterio de salida — NO avanzar hasta comprobar:**
- ✅ Mismo conteo de archivos (blob vs tabla)
- ✅ Mismo conteo de unidades (blob vs tabla)
- ✅ Misma distribución de riesgo
- ✅ Misma cantidad de reglas derivadas
- ✅ Mismas entidades sincronizadas a A-ONE en shadow mode

---

### Fase 3 — Workers por Etapa

> Pipeline desacoplado con etapas persistidas y reintentables.

**Archivos a modificar:**

| Archivo | Cambio |
|---|---|
| [pipeline.py](file:///c:/INI_Code-Agent/src/core/analyzers/pipeline.py) | Refactorizar en 4 funciones: `run_extract()`, `run_enrich()`, `run_security()`, `run_sync()` |
| [worker_pool.py](file:///c:/INI_Code-Agent/src/core/analyzers/worker_pool.py) | `run_parallel_enrichment()` escribe a BD vía upsert |
| [scan.py](file:///c:/INI_Code-Agent/src/api/routes/scan.py) | Eliminar `_build_results()`, eliminar 3 endpoints enrich, simplificar background task |
| `src/core/workers/` [NUEVO] | Módulo de workers por etapa (opcional para V3.1 con cola durable) |

**Criterio de aceptación:**
- Si se interrumpe ENRICH, al reintentar no se repite EXTRACT
- `scan_stages` muestra el estado correcto de cada etapa
- `_run_scan_background_task()` tiene menos de 50 líneas

---

### Fase 4 — Sync Shadow a A-ONE

> Sync con IDs determinísticos y trazabilidad.

**Archivos a modificar:**

| Archivo | Cambio |
|---|---|
| [aone_client.py](file:///c:/INI_Code-Agent/src/core/integration/aone_client.py) | Recibir `escaneo_id` en vez de `job_results: dict`. Leer de BD local. Eliminar `uuid.uuid4()` |
| [repository.py](file:///c:/INI_Code-Agent/src/db/repository.py) | Agregar `create_sync_attempt()`, `get_sync_attempts()` |

**Criterio de aceptación:**
- Cero `uuid.uuid4()` en `sync_scan_results()`
- Re-sincronizar el mismo scan no duplica datos en A-ONE
- Cada intento queda registrado en `sync_attempts`

---

### Fase 5 — API V2

> Endpoints paginados y operables.

**Archivos a crear/modificar:**

| Archivo | Cambio |
|---|---|
| `src/api/routes/scan_v2.py` [NUEVO] | Endpoints V2 con paginación y filtros |
| `src/api/schemas/scan_response.py` | Agregar schemas de respuesta paginada |
| [repository.py](file:///c:/INI_Code-Agent/src/db/repository.py) | Agregar queries con filtros, paginación y JOINs |
| [main.py](file:///c:/INI_Code-Agent/src/api/main.py) | Registrar router V2 |

**Criterio de aceptación:**
- `GET /api/v2/scan/{id}` devuelve resumen <1KB
- `GET /api/v2/scan/{id}/unidades?risk=HIGH` responde en <200ms
- Paginación con `total`, `page`, `limit`, `items`
- `POST /api/v2/scan/{id}/retry-stage/{stage}` reintenta solo la etapa especificada

---

### Fase 6 — Cutover

> A-ONE consume el modelo nuevo. V1 se depreca.

| Tarea | Detalle |
|---|---|
| Shadow comparison | Validar que V2 produce los mismos resultados que V1 |
| Migrar consumidores de V1 a V2 | Actualizar clientes |
| A-ONE lee de modelo normalizado | No más blob |

---

### Fase 7 — Contract y Limpieza Final

> Eliminar código y datos obsoletos.

| Tarea | Archivo |
|---|---|
| Eliminar columna `results` de `ScanJobORM` | `src/db/models.py` |
| Eliminar `_build_results()` | `src/api/routes/scan.py` |
| Eliminar endpoints V1 de enrich | `src/api/routes/scan.py` |
| Eliminar `_rebuild_project_context()` | `src/api/routes/scan.py` |
| Eliminar `src/integrations/aone_client.py` (duplicado) | Archivo completo |
| Restringir CORS | `src/api/main.py` |
| Tarea de limpieza de `repos_cache` | `src/api/main.py` (lifespan) |
| Agregar índices | `risk_level`, `archivo_id`, `escaneo_id` |

---

## 13. Feature Flags

Cada fase se controla con un feature flag en `config.py`:

```python
# Fase 1-2
enable_normalized_write: bool = False      # Escribir a tablas normalizadas
enable_dual_write: bool = False            # Doble escritura (blob + tablas)

# Fase 3
enable_stage_workers: bool = False         # Pipeline por etapas
enable_llm_auto_enrich: bool = False       # LLM integrado en pipeline
enable_semgrep_stage: bool = False         # Semgrep como etapa independiente

# Fase 4
enable_aone_sync_v2: bool = False          # Sync con IDs determinísticos

# Fase 5
enable_scan_api_v2: bool = False           # Endpoints V2
```

---

## 14. Observabilidad Mínima

### Métricas obligatorias

| Métrica | Tipo |
|---|---|
| `scans_created_total` | Counter |
| `scan_stage_duration_seconds` | Histogram (por stage) |
| `scan_total_duration_seconds` | Histogram |
| `scan_stage_failures_total` | Counter (por stage) |
| `scan_retries_total` | Counter (por stage) |
| `llm_cost_per_scan` | Gauge |
| `llm_latency_seconds` | Histogram |
| `semgrep_findings_total` | Counter (por severity) |
| `aone_sync_failures_total` | Counter |
| `scan_queue_depth` | Gauge |

### Logs estructurados (siempre incluir)

```json
{
  "job_id": "uuid",
  "escaneo_id": "uuid",
  "stage": "EXTRACT|ENRICH|SECURITY|SYNC",
  "attempt": 1,
  "worker_id": "worker-1",
  "commit_hash": "abc123..."
}
```

### Tracing

Cada etapa debe llevar el **mismo `trace_id`** para correlación end-to-end.

---

## 15. Riesgos y Mitigaciones

| # | Riesgo | Mitigación |
|---|---|---|
| 1 | Job huérfano por caída del proceso | Cola durable + worker stateless |
| 2 | Duplicación de reglas o sync | IDs determinísticos + unique constraints + idempotency key |
| 3 | Cambio de modelo/prompts LLM rompe esquema | Columnas derivadas + raw payload versionado en `llm_runs` |
| 4 | Consumers ocultos del blob `results` | Doble escritura + deprecación gradual |
| 5 | Semgrep falla y deja estado ambiguo | Stage independiente con estado propio en `scan_stages` |
| 6 | Rollback de fases intermedias | Feature flags permiten desactivar cada fase independientemente |

---

## 16. Arquitectura AWS Ideal (Visión Futura)

> [!NOTE]
> Esta sección describe la arquitectura de producción ideal. El V3 actual se implementa primero en la infraestructura existente y puede evolucionar hacia esta visión.

| Componente | Servicio AWS | Rol |
|---|---|---|
| Ingesta | API Gateway + Lambda/Fargate | Recibe `POST /scan`, encola |
| Orquestación | AWS Step Functions | Controla flujo de 4 stages con reintentos exponenciales |
| Cómputo | Fargate Workers | AST Extraction, manejo de repos grandes |
| Inteligencia | Amazon Bedrock | Procesamiento asíncrono LLM |
| Persistencia | RDS PostgreSQL | Tablas normalizadas + JSONB para detalles |
| Cola | SQS | Cada stage tiene su cola |
| Observabilidad | CloudWatch + X-Ray | Métricas, logs, tracing |

### Revisión Well-Architected

| Pilar | V2 Actual | V3 Propuesto |
|---|---|---|
| Fiabilidad | 🔴 Fallo en un paso rompe todo | ✅ Step Functions con reintentos |
| Eficiencia | 🔴 Re-procesa todo siempre | ✅ Content hashing, cache por hash |
| Excelencia Operacional | 🔴 Sin limpieza, sin métricas | ✅ Lifecycle policies, CloudWatch |
| Seguridad | 🟡 CORS abierto | ✅ IAM Roles granulares |

---

## 17. Resultado Esperado

| Característica | Antes (V1/V2) | Después (V3) |
|---|---|---|
| Escalabilidad | Baja | Alta |
| Consultabilidad | Nula (blob) | Completa (SQL + filtros) |
| Resiliencia | Baja (todo o nada) | Alta (reintentos parciales) |
| Idempotencia | Parcial (`uuid.uuid4()`) | Completa (SHA-256 determinísticos) |
| Observabilidad | Baja | Alta (métricas + logs + tracing) |
| Operabilidad API | Solo consulta | Consulta + retry + stages |
| Auditoría LLM | Inexistente | Completa (`llm_runs`) |
| Migración | Big bang | Expand/Contract seguro |

---

## 18. Resumen de Cambios por Archivo

| Archivo | Acción | Fase |
|---|---|---|
| `src/db/models.py` | Agregar 8 modelos ORM nuevos, mantener `results` temporal | 1 |
| `src/db/repository.py` | Agregar CRUD con upsert + queries paginadas | 1, 2, 4, 5 |
| `src/core/analyzers/pipeline.py` | Refactorizar en 4 stages, recibir `session`, IDs determinísticos | 2, 3 |
| `src/core/analyzers/worker_pool.py` | Completar `run_parallel_enrichment()` con escritura a BD | 3 |
| `src/api/routes/scan.py` | Simplificar background task, eliminar `_build_results()` y enrich endpoints | 3, 7 |
| `src/api/routes/scan_v2.py` | **[NUEVO]** Endpoints V2 paginados y operables | 5 |
| `src/api/schemas/scan_response.py` | Agregar schemas paginados | 5 |
| `src/core/integration/aone_client.py` | Leer de BD, IDs estables, registrar `sync_attempts` | 4 |
| `src/config.py` | Agregar feature flags V3 | 1 |
| `src/api/main.py` | CORS restringido, limpieza repos_cache, router V2 | 5, 7 |
| `src/integrations/aone_client.py` | **[ELIMINAR]** (duplicado) | 7 |

---

## 19. Conclusión y Recomendación

> **"Aprobamos la refactorización en su dirección funcional, pero no aprobamos la implementación V2 tal como está. Se reemplaza por V3 con arquitectura por etapas, migración expand/contract, idempotencia, telemetría y compatibilidad transitoria."**

El Plan V3 mantiene las mejoras del Plan V2 (normalización, eliminación del blob, endpoints paginados, pipeline automático) pero agrega lo necesario para un sistema de producción:

- ✅ Pipeline resiliente por etapas
- ✅ Workers desacoplados
- ✅ Idempotencia real con SHA-256
- ✅ Auditoría LLM completa
- ✅ Migración segura Expand/Contract
- ✅ API operable (retry, stages)
- ✅ Observabilidad (métricas, logs, tracing)
- ✅ Feature flags para rollout gradual

**Resultado:** Arquitectura aprobable para producción.

---

## 20. Plan de Verificación

### Tests Automatizados
- **Fase 1:** Script SQL que valida existencia de tablas y constraints
- **Fase 2:** Test de paridad blob vs tablas normalizadas (mismo conteo)
- **Fase 3:** Test de reintento: forzar fallo en ENRICH, verificar que EXTRACT no se repite
- **Fase 4:** Test de idempotencia: ejecutar sync 3 veces, verificar que A-ONE tiene exactamente los mismos datos
- **Fase 5:** Tests de integración para cada endpoint V2 con filtros y paginación

### Verificación Manual
- Ejecutar `POST /scan` de un microservicio conocido
- Verificar datos en DBeaver en todas las tablas nuevas
- Comparar conteos blob vs tablas con query SQL
- Probar `retry-stage` desde la API V2
- Validar que CORS ya no es `*` en la Fase 7

---

*Code-Agent V3.0 — "The Resilient Agent" — Plan de Refactorización para aprobación técnica*
﻿
---

## 21. Anexo A — Respuestas a las 10 Observaciones del Comité (V3.1)

El comité técnico de arquitectura revisó la V3.0 el 2026-03-12 y determinó que el diseño es "aprobable para desarrollo, pero no para producción masiva". A continuación se presentan las resoluciones de arquitectura (V3.1) a las 10 costuras identificadas.

### 1. Identidad Histórica vs Identidad Técnica (Idempotencia)

> **Observación:** El ID propuesto (`sha256(repo_url + ... + commit_hash)`) resuelve la idempotencia técnica por scan, pero rompe la trazabilidad histórica. Para medir evolución, la entidad lógica debe sobrevivir entre commits.

**Resolución V3.1:** 
Se separan los conceptos de **Identidad Histórica** e **Instancia Fáctica**.
- `unidad_logica_id`: Identificador temporal/histórico. Se calcula SIN el `commit_hash`.
  - Fórmula: `sha256(repo_url + branch + ruta_archivo + nombre + tipo)`
- `scan_snapshot_id`: Identificador de la versión exacta observada en el análisis actual.
Al diseñar el UPSERT, actualizamos la `unidad_logica` existente (manteniendo trazabilidad histórica) pero registramos el cambio en una nueva tabla de historial `unidad_logica_snapshots` para retener la "versión observada en el scan".

### 2. Estado Granular y Reintentos Parciales en Etapas (Fan-Out)

> **Observación:** Las etapas ENRICH y SECURITY procesan miles de items. Si fallan 20 de 1000, un estado general en `scan_stages` es insuficiente para saber qué reintentar.

**Resolución V3.1:**
- `scan_stages.status` será estricto: `SUCCEEDED` (100% éxito), `PARTIAL` (>0% fallos), `FAILED` (100% fallos o fallo catastrófico).
- Se introduce la tabla de tracking granular `stage_items` (insertada masivamente en Memcached/Redis o tabla Unlogged temporal en Postgres).
- El reintento de un stage `PARTIAL` no reejecuta la lógica sobre todo el lote, sino que ejecuta una query delta: `SELECT unidades WHERE id NO EN (items_exitosos_del_stage)`.

### 3. Rate Limiting, Concurrencia y Cuello de Botella LLM

> **Observación:** No hay gobierno de la concurrencia ni protección de "backpressure" contra las cuotas del proveedor de LLM (Bedrock).

**Resolución V3.1:**
- **Control de Concurrencia:** El worker de ENRICH no usará `asyncio.gather` puro sobre todos los archivos. Implementará una cola SQS intermedia (`enrich_tasks_queue`) o un semáforo global distribuido (Redis limiter).
- **Rate Limit y Backpressure:** Se implementa el patrón Token Bucket a nivel de aplicación (ej. máx 50 req/sec globales al LLM). Si se recibe `429 Too Many Requests`, se aplica Exponential Backoff con Jitter a nivel de worker y se suspende temporalmente el consumo de la cola.
- **Circuit Breaker:** Si el proveedor degrada (ej. 5% de 5xx), se abre el circuito, el stage pasa a `FAILED` o `PAUSED`, y los jobs se retienen en cola sin consumir compute.

### 4. Almacenamiento Separado para Raw Output (PostgreSQL vs S3)

> **Observación:** Guardar `raw_output` del LLM en la base transaccional (`llm_runs`) inflará los backups, IOPS y costos de storage. 

**Resolución V3.1:**
- **Política Estricta:** PostgreSQL **NUNCA** guardará el raw JSON o output natural del LLM > 255 caracteres en la tabla `llm_runs`.
- `llm_runs.raw_output` desaparece. Se reemplaza obligatoriamente por `s3_object_key`.
- Los workers subirán en streaming asíncrono los resultados del LLM a un bucket S3 de retención corta y solo guardarán el puntero en PostgreSQL para propósitos de auditoría pura.

### 5. Caché Semántico: Composibilidad de la Cache Key

> **Observación:** El caché condicionado solo al `content_hash` servirá enriquecimientos obsoletos si cambia el prompt, el modelo o los parámetros.

**Resolución V3.1:**
La clave del caché de LLM (Redis o tabla `llm_cache`) no será solo el hash del código.
- `cache_key = sha256(content_hash + model_name + prompt_version + max_tokens_config)`
Cualquier despliegue que altere la instrucción al LLM (incluso sutilmente) requerirá un bump en `prompt_version`, lo que invalidará automáticamente todos los cachés antiguos de forma limpia.

### 6. Resolución de Conflictos: Jerarquía de la Fuente de Verdad

> **Observación:** Durante la doble escritura (Fase 2) y sync (Fase 4), si hay discrepancia entre el blob, el modelo relacional o A-ONE, ¿quién manda?

**Resolución V3.1:**
- **Lectura:** El sistema consumidor (API) lee exclusivamente del modelo transaccional nuevo desde el momento en que se aprueba la Fase 3.
- **Escritura:** El modelo transaccional nuevo (las tablas V3) **es la fuente de verdad absoluta e irrefutable**. 
- El blob `results` pasa a ser *Write-Only* operativamente (se escribe para retrocompatibilidad, nunca se usa para toma de decisiones internas).
- A-ONE es estrictamente un **Replica Receiver**. Si falla un sync, se descarta el estado de A-ONE y se re-sincroniza forzadamente desde el modelo V3.

### 7. Estrategia de Rollback de Datos (Soft Delete vs Hard Reset)

> **Observación:** Si en plena migración gradual se descubre un fallo de lógica, ¿cómo se deshacen escrituras masivas en DB?

**Resolución V3.1:**
- Rollback de la aplicación: fácil mediante feature flags.
- Rollback de datos:
  - Todo scan emitido bajo un feature flag experimental se marcará con `schema_version = 'v3_beta'`.
  - Las tablas append-only (`llm_runs`, `scan_stages`, `sync_attempts`) se truncan por partición o se borran masivamente con la condición de versión.
  - Para tablas con estado activo (`unidades_logicas`), la doble escritura de la Fase 2 incluye una tabla de sombra (`unidades_logicas_v2`). En caso de abortar la migración, la app vuelve a leer de `results` o de las tablas V2 puras. Los datos corruptos V3 se purgan offline sin afectar uptime.

### 8. Retención (Lifecycle) y Particionamiento de Datos

> **Observación:** Falta una política formal de limpieza para evitar que la base operativa se vuelva un data lake inmanejable.

**Resolución V3.1:**
- **Particionamiento:** Las tablas de alto volumen (`llm_runs`, `security_findings`, `sync_attempts`, `scan_stages`) se particionarán nativamente por rango de fecha (mensual `PARTITION BY RANGE (created_at)`).
- **Data Lifecycle (TTL):**
  - **30 días:** Retención de detalle granular transitorio (`llm_runs`, logs de sync, stages). Las particiones del mes pasado se hacen DROP automático (cero I/O comparado con DELETE).
  - **90 días:** Retención en S3 de los raw outputs del LLM (Lifecycle rule de AWS S3).
  - **Permanente:** Agregaciones a nivel de `escaneos`, última versión activa de la `unidad_logica`, y tablas dimensionales maestras.

### 9. Manejo de Repositorios Extremos (Desbordamiento I/O)

> **Observación:** Repos enormes, submodules, vendorización y LFS pueden bloquear el pipeline o hacer fallar el análisis.

**Resolución V3.1:**
El Extract Worker no confiará ciegamente en el checkout. Implementará protecciones duras:
1. **Shallow Clone Obligatorio:** `git clone --depth 1`. No se trae historial completo.
2. **LFS Ignorado:** No descargar binarios. Export config global de git.
3. **Vendor/Generated Exclusion:** Integración estricta con `.gitignore`, `.codeagentignore`. Autodetección de carpetas `node_modules/`, `vendor/`, `migrations/`.
4. **Timeout de Checkout & Parsing:** Límite máximo de clonado y tamaño de proyecto. Un proyecto que exceda límites configurables rechazará encolarse o generará estado `FAILED` explícito en `EXTRACT` (fail-fast, no bloqueo del orquestador).

### 10. Calibración Empírica de Fórmulas y Scoring

> **Observación:** La fórmula propuesta (`overall_score`) es heurística. Se necesita evidencia para justificar pesos ante el equipo de arquitectura.

**Resolución V3.1:**
- La fórmula incluida en el documento es el "Baseline 1.0".
- En Fase 0 (diagnóstico), se insertará un job offline para ejecutar la fórmula Baseline contra los 100 proyectos más recientes del histórico de A-ONE.
- El resultado se comparará con los incidentes en producción (o tickets de bug) reportados de esos mismos proyectos (si se cuenta con integraciones Atlassian/Jira o el conocimiento de los Tech Leads).
- Se afinarán los modificadores (el peso de la complejidad vs peso de seguridad) no por opinión, sino por correlación lineal empírica documentada. El score ya no será heurístico, sino ajustado por datos reales de los incidentes de la corporación.
