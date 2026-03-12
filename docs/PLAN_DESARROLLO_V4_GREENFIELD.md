# Plan de Desarrollo y Arquitectura V4 — Code-Agent
## Proyecto Greenfield: "The Strangler" (V4.3 - The Ironclad)

**Estado:** Documento Fundacional para Agentes y Desarrolladores (Revisión Arquitectura V4.3)
**Objetivo:** Construir Code-Agent V4 desde cero como un proyecto independiente. Esta versión aplica un "Downscoping Operativo", implementa volúmenes compartidos (EFS) para latencia nula, un Linker algorítmico, y un balance pragmático entre pureza relacional y consultabilidad analítica, preparado para reemplazar a V1.

---

## 1. Visión del Sistema
Code-Agent V4 es una plataforma de análisis estático y dinámico de código asistido por IA. Su propósito es escanear repositorios, extraer su estructura (AST), evaluar reglas de seguridad (Semgrep) y usar Modelos de Lenguaje (LLM) para enriquecer el contexto, calificar riesgos y finalmente sincronizar estos hallazgos con un sistema externo (A-ONE).

El diseño prioriza la **simplicidad operable y velocidad de I/O**:
1. **Identidad Histórica Realista:** Un Linker ponderado sobre código normalizado (Jaccard Index).
2. **Pipeline de Cero Latencia I/O:** Los repositorios se clonan una sola vez en un volumen EFS compartido entre workers, eliminando las lentas compresiones y descargas a S3.
3. **Control de Costos y Rate Limiting:** Protección activa contra el exceso de peticiones LLM y tamaño de repos.
4. **Pragmatismo de Base de Datos:** PostgreSQL funciona como RDBMS puro para operación y metadatos indexables (filtros), delegando los textos inmensos (Outputs LLM) a S3.

---

## 2. Pila Tecnológica (Stack Operacional)
* **Backend:** Python 3.11+, FastAPI (Solo para Ingesta y Polling de estado).
* **Base de Datos Operacional:** PostgreSQL (Relacional estricto enriquecido con tags/filtros JSONB básicos).
* **Pool de Conexiones (Nuevo V4.5):** **Amazon RDS Proxy**. Obligatorio para evitar el agotamiento de conexiones (Connection Exhaustion) cuando 50 workers de Fargate intenten escribir simultáneamente.
* **Storage Artifacts Pesados:** AWS S3 (Bucket con Lifecycle Policies estrictas de 90 días para "resumenes").
* **Storage de Workspaces (Nuevo V4.3):** AWS EFS (Elastic File System) montado dinámicamente en los workers, o Mountpoint for Amazon S3 para evitar latencia de descarga/compresión en cada etapa.
* **Orquestación de Flujo de Trabajo:** **AWS Step Functions**. Define la máquina de estados, transiciones atómicas y reintentos sin sobrecargar la API REST con polling interno.
* **Integraciones Core:** 
  * Git (Shallow clones puntuales).
  * Semgrep (AWS Fargate o Lambda atado a EFS).
  * Amazon Bedrock / Claude 3 (LLM) alojado en VPC Endpoints.

---

## 3. Modelo de Datos V4.3 (Pragmático e Indexable)

### 3.1. Tracking de Ejecución (Cabeceras)
#### `scan_jobs`
| Columna | Tipo | Descripción |
|---|---|---|
| `id` | UUID PK | ID del job |
| `status` | VARCHAR(20) | `QUEUED`, `RUNNING`, `COMPLETED`, `FAILED` |
| `activo_id` | VARCHAR(36) | FK referencial a A-ONE |
| `aplicacion_id` | VARCHAR(36) | FK referencial a A-ONE |
| `microservice_name` | VARCHAR(255) | Nombre legible |
| `project_path` | TEXT | Ruta en EFS (`/mnt/efs/workspaces/{job_id}/`) |
| `branch` | VARCHAR(100) | Rama analizada |
| `commit_hash` | VARCHAR(40) | Hash exacto |
| `error_message` | TEXT | Error si FAILED |
| `created_at` | TIMESTAMP | |
| `completed_at` | TIMESTAMP | |

#### `escaneos`
> 1 fila por ejecución. Guarda **tags de búsqueda y métricas base** en JSONB para la UI, pero el payload pesado va a S3.

| Columna | Tipo | Descripción |
|---|---|---|
| `id` | UUID PK | |
| `job_id` | UUID FK | → `scan_jobs.id` |
| `score_general` | DECIMAL(5,2) | Calculo final ponderado |
| `nivel_riesgo` | VARCHAR(10) | `CRITICAL`, `HIGH`, `MEDIUM`, `LOW` |
| `metricas_busqueda` | JSONB | Tags indexables: `{langs: ['py'], frameworks: ['django']}` |
| `archivos_total` | INT | |
| `funciones_total` | INT | |
| `informe_s3_uri` | TEXT | Enlace al JSON analítico masivo de 10 mil líneas. |
| `escaneado_en` | TIMESTAMP | |

### 3.2. Identidad Histórica (Anclas Permanentes)
#### `unidades_logicas`
| Columna | Tipo | Descripción |
|---|---|---|
| `id` | UUID PK | ID histórico permanente. |
| `repo_url` | TEXT | URL del repositorio. |
| `nombre_identidad` | VARCHAR(255) | Nombre original de la función/clase. |
| `tipo` | VARCHAR(20) | `CLASE` o `FUNCION`. |
| `path_original` | TEXT | Primera ruta donde se detectó. |
| `created_at` | TIMESTAMP | Fecha de nacimiento de la identidad. |
| `last_seen_at` | TIMESTAMP | Fecha del último scan activo. |

### 3.3. Observaciones Temporales (Snapshots)
#### `archivos_fuente`
| Columna | Tipo | Descripción |
|---|---|---|
| `id` | UUID PK | Hash de (repo + ruta + commit_hash) |
| `escaneo_id` | UUID FK | → `escaneos.id` |
| `nombre` | VARCHAR(255) | |
| `ruta_archivo_actual` | TEXT | Ruta relativa |
| `lenguaje` | VARCHAR(20) | |
| `lineas_codigo` | INT | |
| `metricas_base` | JSONB | Conteo rápido de clases, funciones y complejidad general. |
| `content_hash` | VARCHAR(64) | SHA-256 del archivo físico |

#### `unidad_logica_snapshots`
| Columna | Tipo | Descripción |
|---|---|---|
| `id` | UUID PK | Hash determinístico: `sha256(unidad_id + commit_hash)` |
| `unidad_id` | UUID FK | → `unidades_logicas.id` |
| `archivo_id` | UUID FK | → `archivos_fuente.id` |
| `commit_hash` | VARCHAR(40) | |
| `content_hash` | VARCHAR(64) | SHA-256 exacto del código para el Linker |
| `normalized_content_hash`| VARCHAR(64) | SHA-256 del código sin espacios/comentarios (Vital para Linker) |
| `overall_score` | DECIMAL(5,2) | Score de esta versión |
| `risk_level` | VARCHAR(10) | |
| `categorias_riesgo` | JSONB | Etiquetas rápidas de búsqueda: `['SQL_INJECTION', 'XSS']` |
| `resumen_s3_uri` | TEXT | Puntero a la respuesta prolija del LLM (Miles de caracteres) |
| `complejidad` | INT | Ciclomática |

### 3.4. Auditoría y Trazabilidad Extrema
#### `llm_runs`
| Columna | Tipo | Descripción |
|---|---|---|
| `id` | UUID PK | |
| `job_id` | UUID FK | → `scan_jobs.id` |
| `snapshot_id` | UUID FK | → `unidad_logica_snapshots.id` |
| `model_name` | VARCHAR(100) | |
| `prompt_version` | VARCHAR(20) | |
| `tokens_input` | INT | Uso facturable |
| `tokens_output` | INT | Uso facturable |
| `latency_ms` | INT | |
| `http_status` | INT | 200, 429, 500 |
| `raw_output_s3_uri` | TEXT | Texto crudo protegido en S3 |
| `created_at` | TIMESTAMP | |

#### `security_findings`
| Columna | Tipo | Descripción |
|---|---|---|
| `id` | UUID PK | |
| `job_id` | UUID FK | → `scan_jobs.id` |
| `snapshot_id` | UUID FK | |
| `rule_id` | VARCHAR(200) | Ej: `python.django.security...` (Perfecto para group-by en DB) |
| `severity` | VARCHAR(20) | `ERROR`, `WARNING` |
| `fingerprint` | VARCHAR(64) | Hash del finding (Idempotency Semgrep) |

#### `sync_attempts`
| Columna | Tipo | Descripción |
|---|---|---|
| `id` | UUID PK | |
| `job_id` | UUID FK | → `scan_jobs.id` |
| `target_system` | VARCHAR(50) | `A-ONE` |
| `idempotency_key` | VARCHAR(128) | UUID garantizado para no duplicar en remoto |
| `attempt` | INT | |
| `status` | VARCHAR(20) | `PENDING`, `SUCCESS`, `FAILED` |
| `http_code` | INT | |

---

## 4. El Orquestador: AWS Step Functions y Volúmenes EFS

El Handoff de S3 (comprimir/descomprimir 50MB entre stages 4 veces seguidas) introduce "Impuesto de Latencia". En su lugar, todos los Fargate/Workers montan **AWS EFS (`/mnt/efs/workspaces/`)**.

**REGLA DEL PASE DE PUNTEROS:** Está estrictamente **PROHIBIDO** que los workers devuelvan arrays de objetos al Step Function (límite duro de 256KB en AWS). El orquestador solo transporta el `job_id`. Cada etapa lee su trabajo de PostgreSQL y escribe sus resultados en DB o EFS. El Step Function es un "director de orquesta", no un camión de mudanza.

### Stage 1: EXTRACT (Resolución, Clonado y Linker Fino)
1. **Validación Atómica de Commit:** Si `commit_hash` no se provee en el Payload, el stage hace un `git ls-remote` para resolverlo al instante. Si se provee, se valida contra el branch. Si es inválido, el job falla elegante sin encender infraestructura pesada.
2. Descarga del código (Shallow clone directo al volumen compartido de EFS en `/mnt/efs/workspaces/{job_id}/`).
3. Se ejecuta el AST parser. Por cada función detectada:
   - Se realiza una **Normalización del Código:** Se eliminan comentarios, docstrings y espacios en blanco.
   - Se computa el `normalized_content_hash`.
4. **Linker Híbrido y el Escudo de Memoria (Short-circuit + Jaccard):** 
   - **Paso A (Salida Rápida):** Si el `normalized_content_hash` es idéntico a una versión previa, hereda la `unidad_logica` inmediatamente (O(1) CPU).
   - **Paso B (Ponderación con Límite RAM):** Si cambió el hash normalizado, se activa el análisis Jaccard (`70% AST Jaccard + 20% nombre + 10% args`). Dado que comparar miles de ASTs consume mucha memoria, el contenedor Fargate debe tener un límite de RAM estricto y procesar en lotes (batching) para evitar un OOM (Out Of Memory). Si el score > 85%, hereda. Si no, nace una nueva identidad.
5. Genera inserciones del snapshot en base de datos PostgreSQL.

### Stage 2: SECURITY (Semgrep Aislado sobre EFS)
1. El worker (AWS Fargate) ingresa directo al path de red compartido de EFS (`/mnt/efs/workspaces/{job_id}/`). **Cero latencia de descarga.**
2. Ejecuta Semgrep.
3. Inserta registros deducidos en la tabla indexable `security_findings` con sus respectivos `rule_id`. 

### Stage 3: ENRICH (Bedrock & Mapeo Temporal)
1. AWS Step Function ejecuta un Map State (parallel fan-out) por cada unidad lógica en el commit. **CRÍTICO:** Configurar `MaxConcurrency: 50` para evitar saturar VPC Endpoints y desencadenar errores HTTP 429 de límite de cuotas en Bedrock.
2. **Caché Semántica:** `CacheKey = SHA256(normalized_content_hash + system_prompt)`.
3. El LLM califica riesgos y redacta. El Score viaja a PostgreSQL (`overall_score` y tags `categorias_riesgo`). El ensayo o resumen pesado va exclusivo a un archivo .txt/.json en **S3**.
4. Si agota retries de API, Step Function continúa y el Job sale como `PARTIAL`.

### Stage 4: SYNC & TEARDOWN
1. Se recolectan los resultados parciales filtrados desde PostgreSQL y se combinan con enlaces puntuales.
2. Sube Payload final de Sync a S3 -> Ejecuta HTTP POST hacia A-ONE usando `idempotency_key`.
3. **Teardown y Reaper de Respaldo:** Una tarea final en el Step Function elimina el `workspace/{job_id}/` del EFS. 
   - *Protección OOM:* Se desplegará una AWS Lambda ("EFS Reaper") programada cada hora que ejecute un barrido de carpetas sin actividad por más de 12 horas, previniendo fugas masivas de almacenamiento si las Step Functions fallan catastróficamente antes de la limpieza.

---

## 5. Shadow Mode (Despliegue Strangler Seguro)

Para que V1 no reviente a V4 y el costo no se duplique innecesariamente:
* Se habilitará un **Ingest Proxy / Rate Limiter** en el endpoint V1.
* Durante la Fase Inicial (BETA), solo el **5%** al **10%** de los análisis de V1 se enviarán concurrentement a V4 en formato "Espejo".
* El equipo técnico utilizará la metadata de `scan_jobs` V4 y la BD analítica V1 para verificar paridad funcional. 

---

## 6. Diseño API V4 (Read Models & Contracts)

### `POST /api/v4/scan`
Crea el job y dispara la máquina de estados en AWS Step Functions. `commit_hash` ahora es Opcional, forzando la resolución remota desde `branch` si se omite.
**Request Body:**
```json
{
  "repo_url": "https://github.com/empresa/microservicio-pagos.git",
  "branch": "main",
  "commit_hash": "a1b2c3d4e5", 
  "microservice_name": "pagos-core"
}
```
**Response (202 Accepted):** 
```json
{ 
  "job_id": "8a7b6c...uuid", 
  "status": "QUEUED" 
}
```

### `GET /api/v4/scan/{job_id}/status`
Consulta rápida (polling) indexada en PG.
**Response (200 OK):**
```json
{
  "job_id": "8a7b6c...uuid",
  "status": "RUNNING",
  "current_stage": "ENRICH",
  "progress_pct": 45
}
```

### `GET /api/v4/units/{unidad_id}/history`
**Response (200 OK):**
```json
{
  "unidad": {
    "id": "e4f5a8...uuid",
    "nombre_identidad": "process_payment_gateway",
    "tipo": "FUNCION"
  },
  "history": [
    {
      "snapshot_id": "sha256-hash-snapshot-1",
      "commit_hash": "a1b2c3d4e5",
      "overall_score": 92.5,
      "categorias_riesgo": ["NETWORK_TIMEOUT"],
      "resumen_s3_url": "s3://bucket-agente/v4/resumen/shasnap1.json",
      "escaneado_en": "2026-03-12T10:15:00Z"
    }
  ],
  "pagination": { "page": 1, "size": 20 }
}
```

---

## 7. Políticas Duras del Sistema y The Golden Equation
### La Ecuación Dorada del Riesgo (The Golden Identity Rule)
Para evitar que el score numérico dependa de fluctuaciones subjetivas del LLM, el cálculo final de riesgo de una Unidad Lógica se deriva de una métrica cínica e inmutable evaluada en el Stage 3:

```math
Score = \max(0, \min(100, 100 - (C \cdot 2) - (S \cdot 10) + D - L - A))
```
- **$C$**: Complejidad Ciclomática (AST).
- **$S$**: Severidad sumada de hallazgos de seguridad (Semgrep).
- **$D$**: Bono (+5) por presencia de documentación sustancial (Docstrings).
- **$L$**: Penalización por exceso de Líneas de Código.
- **$A$**: Penalización por acoplamiento alto (Múltiples accesos BD / External APIs).


Si eres una IA o Desarrollador Sénior escribiendo código para V4:

1. **EL PRAGMATISMO RELACIONAL:** No metas payloads inmensos de Bedrock dentro de columnas de PG (Eso va a S3). Pero **SÍ** debes guardar y estructurar tags indexables, contadores y arrays de metadatos (ej: `['SQL_INJ']`, `rule_ids`) en columnas JSONB para que el sistema tenga analítica cruzada instantánea sin leer el storage y pueda armar Dashboards eficientes.
2. **WORKSPACES DE BAJA LATENCIA (EFS):** Evita empaquetar en `.tar.gz` todo y empujarlo a S3 para descargarlo 3 segundos después. Usa volúmenes compartidos para el pasamanos del código crudo y elimínalos en el Teardown.
3. **CERO ESTADO HÍBRIDO EN FASTAPI:** FastAPI es estúpido (Stateless). Se limita a recibir solicitudes, validar commits atónimcos remotos (ls-remote) e iniciar flujos en AWS Step Functions.
4. **LINKER DECISIVO Y LIMPIO:** El historial no se rompe por una indentación. El `normalized_content_hash` limpia docstrings y formatos. Se usa similitud cruzada Jaccard. Si supera 85%, es la misma función.
5. **IDEMPOTENCIA GARANTIZADA:** TODO insert masivo en tablas usa `INSERT ... ON CONFLICT DO UPDATE`. Si el Job se reinicia tras un blackout de AWS, el pipeline no fallará por Primary Keys duplicadas ni creará falsos historiales.

---
*V4.3 The Ironclad: Una arquitectura que puede ser mantenida desde CLI a las 3 de la mañana por un solo devops fatigado sin tener que revisar bases de datos fracturadas o latencias espeluznantes.*
