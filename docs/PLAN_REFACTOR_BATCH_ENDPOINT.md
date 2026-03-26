# Plan de Refactor — POST /api/v1/scan/batch

## Objetivo

Hacer que `/api/v1/scan/batch` sea funcionalmente idéntico a `/api/v1/scan` con la única diferencia de que acepta múltiples bodies (array de `ScanRequest`). Cada scan es independiente, se encola por separado y devuelve su propio `job_id`.

---

## Estado actual vs estado deseado

| Aspecto | Actual | Deseado |
|---|---|---|
| Validación `repo_url` dominio | ❌ No existe | ✅ Igual que scan individual |
| Validación `project_path` local | ❌ No existe | ✅ Igual que scan individual |
| Ejecución background | Secuencial via `_run_batch_background_task` | Paralela — cada scan con su propio `background_tasks.add_task` |
| Respuesta del POST | `{batch_id, total_scans, jobs[]}` | `list[{job_id, microservice_name, status, message}]` |
| `batch_id` | Se genera y guarda en ORM | Eliminado — no se usa |
| `GET /batch/{batch_id}` | Existe, score siempre null | Eliminado |
| Sync a A-ONE | Heredado del scan individual ✅ | Sin cambios |
| Persistencia ORM local | Heredado del scan individual ✅ | Sin cambios |

---

## Archivos a modificar

### 1. `src/api/routes/scan_batch.py` — reescritura del POST y eliminación del GET batch

**Eliminar:**
- Función `_run_batch_background_task` — ya no se necesita
- Endpoint `GET /batch/{batch_id}` — ya no aplica sin batch_id
- Import de `uuid_mod` — ya no se genera batch_id
- Variable `batch_id` en todo el archivo

**Modificar `batch_scan` (el POST):**

Antes de crear cualquier job, iterar cada `scan_req` y aplicar las mismas validaciones que tiene `run_scan` en `scan.py`:

```python
# Validación 1 — repo_url dominio permitido
if scan_req.repo_url:
    parsed_url = urlparse(scan_req.repo_url)
    domain = parsed_url.netloc.split(':')[0]
    allowed_domains = [d.strip() for d in settings.allowed_git_domains.split(',')]
    if not any(domain.endswith(d) for d in allowed_domains):
        raise HTTPException(
            status_code=403,
            detail=f"Scan #{idx+1} ({scan_req.microservice_name}): domain '{domain}' not allowed"
        )

# Validación 2 — project_path existe localmente
if not scan_req.repo_url and not os.path.isdir(scan_req.project_path):
    raise HTTPException(
        status_code=400,
        detail=f"Scan #{idx+1} ({scan_req.microservice_name}): project_path does not exist: {scan_req.project_path}"
    )
```

Luego crear el job y encolarlo directamente con `background_tasks.add_task` (igual que el scan individual), **sin** pasar `batch_id`:

```python
job = await repository.create_scan_job(
    session,
    activo_id=scan_req.activo_id,
    aplicacion_id=scan_req.aplicacion_id,
    microservice_name=scan_req.microservice_name,
    project_path=scan_req.project_path,
    branch=scan_req.branch,
    # sin batch_id
)
background_tasks.add_task(_run_scan_background_task, job.id, scan_req)
```

**Respuesta del POST:**
```json
[
  {
    "job_id": "uuid-1",
    "microservice_name": "svc-A",
    "status": "QUEUED",
    "message": "Scan job queued successfully"
  },
  {
    "job_id": "uuid-2",
    "microservice_name": "svc-B",
    "status": "QUEUED",
    "message": "Scan job queued successfully"
  }
]
```

**Mantener sin cambios:**
- `DELETE /{job_id}/cleanup` — sigue siendo útil e independiente del batch

---

### 2. `src/db/repository.py` — dos cambios

**2a.** Eliminar el parámetro `batch_id` de la firma de `create_scan_job` y de la construcción del `EscaneoORM`.

```python
# Antes
async def create_scan_job(session, *, activo_id, aplicacion_id, ..., batch_id=None)

# Después
async def create_scan_job(session, *, activo_id, aplicacion_id, ...)
```

**2b.** Eliminar la función `list_batch_jobs` (líneas 128-138) — sin `GET /batch/{batch_id}` nadie la llama y queda código muerto.

```python
# Eliminar completamente:
async def list_batch_jobs(
    session: AsyncSession,
    batch_id: str,
) -> list[EscaneoORM]:
    ...
```

---

### 3. `src/db/models.py` — evaluar si eliminar `batch_id` del ORM

El campo `batch_id: Mapped[str | None]` existe en `EscaneoORM`. Si ya no se usa en ningún lado, se puede eliminar de la clase Python. **No requiere migración de BD** porque es nullable — la columna puede quedar en la tabla sin usarse, o eliminarse con una migración si se desea limpiar.

**Decisión:** dejar la columna en la BD (no hacer migración), solo eliminar el campo del ORM Python para que no confunda.

---

### 4. `src/api/schemas/scan_request.py` — sin cambios

`BatchScanRequest` ya es correcto: `scans: list[ScanRequest]`. No se toca.

---

## Lo que NO cambia

- `_run_scan_background_task` en `scan.py` — el batch lo reutiliza, no se toca
- Todo el flujo de pipeline, persistencia en PostgreSQL y sync a A-ONE — heredado automáticamente
- `GET /api/v1/scan/{job_id}` — para consultar cada job individualmente después del batch
- `POST /{job_id}/enrich-all`, `POST /{job_id}/enrich-files` — aplican igual a jobs creados por batch

---

## Flujo resultante

```
POST /api/v1/scan/batch
  │
  ├── Validar cada scan_req (dominio + path)  ← NUEVO
  ├── Crear job en infra.escaneos (status=QUEUED)
  ├── background_tasks.add_task(_run_scan_background_task, job.id, scan_req)
  └── Responder list[{job_id, microservice_name, status, message}]

Cada background task (independiente):
  ├── Clonar repo (si repo_url)
  ├── Idempotency check por commit_hash
  ├── run_pipeline()
  ├── Persistir archivos + unidades en PostgreSQL
  └── sync_scan_results() → A-ONE remoto (si aone_sync_mode=remote)
```

---

## Resumen de cambios por archivo

| Archivo | Tipo de cambio |
|---|---|
| `src/api/routes/scan_batch.py` | Reescritura del POST, eliminar GET batch, eliminar `_run_batch_background_task` |
| `src/db/repository.py` | Eliminar parámetro `batch_id` de `create_scan_job` + eliminar función `list_batch_jobs` |
| `src/db/models.py` | Eliminar campo `batch_id` del ORM Python (columna BD queda intacta) |
| `src/api/schemas/scan_request.py` | Sin cambios |
| `src/api/routes/scan.py` | Sin cambios |
