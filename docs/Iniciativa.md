# Plan de Implementación Code-Agent V4.1 — "The Strangler"
**Enfoque:** Greenfield con Reemplazo Gradual + Trazabilidad Histórica
**Estado:** Aprobado para Construcción
**Versión:** 4.1 (Marzo 2026)

---

## 1. Visión de la Identidad Histórica
El problema de la V1 es que si movías una función de archivo, el sistema perdía su historia. En la V4, separamos la **Identidad Permanente** de la **Observación Temporal**.

* **Unidad Lógica (Permanente)**: Representa el concepto de la función. Su ID no cambia si el código cambia ligeramente.
* **Snapshot (Temporal)**: Representa cómo se veía esa función en un commit específico.



---

## 2. Esquema Técnico de Persistencia (SQL)

### 2.1 Tabla: `unidades_logicas` (El Ancla Histórica)
> Esta tabla guarda la "esencia" de la función. Si la función se mueve de archivo pero mantiene su nombre y propósito, intentamos mantener este ID.

| Columna | Tipo | Descripción |
|---|---|---|
| `id` | UUID PK | ID histórico permanente. |
| `repo_url` | TEXT | URL del repositorio. |
| `nombre_identidad` | VARCHAR(255) | Nombre original de la función/clase. |
| `tipo` | VARCHAR(20) | `CLASE` o `FUNCION`. |
| `path_original` | TEXT | Primera ruta donde se detectó. |
| `created_at` | TIMESTAMP | Fecha del primer escaneo donde apareció. |
| `last_seen_at` | TIMESTAMP | Fecha del último scan donde se confirmó su existencia. |

### 2.2 Tabla: `unidad_logica_snapshots` (La Realidad del Commit)
> Aquí es donde vive el análisis real. Cada scan genera una nueva fila aquí vinculada al ancla de arriba.

| Columna | Tipo | Descripción |
|---|---|---|
| `id` | UUID PK | ID determinístico: `sha256(unidad_id + commit_hash)`. |
| `unidad_id` | UUID FK | → `unidades_logicas.id`. |
| `escaneo_id` | UUID FK | → `escaneos.id`. |
| `commit_hash` | VARCHAR(40) | Hash del commit analizado. |
| `ruta_archivo_actual`| TEXT | Ruta donde está la función en este commit específico. |
| `content_hash` | VARCHAR(64) | SHA-256 del código fuente exacto (para caché semántico). |
| `overall_score` | DECIMAL(5,2) | Score calculado para esta versión. |
| `resumen` | TEXT | Generado por LLM (puntero a S3). |
| `linea_inicio` | INT | Ubicación física en este commit. |

---

## 3. Lógica de Resolución de Identidad (El "Linker")

Cuando el **Extract Worker** detecta una función, sigue este flujo de decisión:

1. **Búsqueda Exacta**: ¿Existe `nombre + tipo + ruta` en `unidades_logicas`?
   - *SÍ*: Vincula al `unidad_id` existente.
2. **Búsqueda de Movimiento (Fuzzy)**: Si no hay búsqueda exacta, ¿existe `nombre + tipo` en el mismo repo pero distinta ruta con un `content_hash` similar (>90%)?
   - *SÍ*: Se asume que la función "se movió". Actualiza `last_seen_at` y vincula al mismo `unidad_id`.
3. **Nueva Identidad**: Si nada coincide, crea una nueva entrada en `unidades_logicas`.

---

## 4. Beneficios Operativos
* **Gráficas de Evolución**: Puedes consultar `SELECT overall_score FROM snapshots WHERE unidad_id = X ORDER BY created_at` para ver si una función está mejorando o empeorando con el tiempo.
* **Ahorro en Bedrock**: Si el `content_hash` de un snapshot nuevo coincide con uno antiguo, el sistema **no llama al LLM** y simplemente copia el resumen anterior.
* **Particionamiento**: La tabla de snapshots se particiona mensualmente, permitiendo borrar datos viejos sin afectar la tabla maestra de unidades.

---

## 5. Próximos Pasos (Fase 1 Greenfield)
1. Ejecutar el script SQL de creación de estas tablas.
2. Implementar la función `generate_identity_hash()` en el worker de extracción.
3. Configurar el **S3 Lifecycle** para que los archivos de `raw_output` asociados a los snapshots se borren después de 90 días.