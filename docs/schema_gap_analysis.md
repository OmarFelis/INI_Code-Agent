# Schema A-ONE vs Respuesta Actual — Gap Analysis

## 1. `archivos_fuente`

| Columna A-ONE | Tipo | En respuesta actual | Estado |
|---|---|---|---|
| [id](file:///d:/Proyectos/INI_Code-Agent/src/models/domain.py#83-103) | UUID_V7 | ❌ no generamos UUID externo | 🔴 Falta |
| `activo_id` | UUID_V7 | ❌ no incluido en response (sí en pipeline) | 🟡 Existe en modelo, no en response |
| `aplicacion_id` | UUID_V7 | ❌ no incluido en response | 🟡 Existe en modelo, no en response |
| `nombre` | VARCHAR(255) | ✅ `nombre` | ✅ OK |
| `ruta_archivo` | TEXT | ✅ `ruta_archivo` | ✅ OK |
| [proposito](file:///d:/Proyectos/INI_Code-Agent/src/core/analyzers/logical_unit_extractor.py#279-299) | VARCHAR(30) | ✅ [proposito](file:///d:/Proyectos/INI_Code-Agent/src/core/analyzers/logical_unit_extractor.py#279-299) | ✅ OK |
| `capa` | VARCHAR(20) | ✅ `capa` | ✅ OK |
| `lenguaje` | VARCHAR(20) | ✅ `lenguaje` | ✅ OK |
| `total_funciones` | INTEGER | ✅ `total_funciones` | ✅ OK |
| `total_clases` | INTEGER | ✅ `total_clases` | ✅ OK |
| `endpoints` | INTEGER | ✅ `endpoints` (conteo) | ✅ OK |
| `operaciones_bd` | INTEGER | ✅ `operaciones_bd` (conteo) | ✅ OK |
| `llamadas_externas` | INTEGER | ✅ `llamadas_externas` (conteo) | ✅ OK |
| `complejidad_ciclomatica` | INTEGER | ✅ `complejidad_ciclomatica` | ✅ OK |
| `lineas_codigo` | INTEGER | ✅ `lineas_codigo` | ✅ OK |
| `resumen` | TEXT | ❌ no incluido en response | 🔴 Falta (se genera en enrich, no se devuelve en archivos) |
| `metadata` | TEXT(JSON) | ❌ no incluido en response | 🔴 Falta (imports, decorators, api_endpoints_detail, etc.) |
| `build_number` | VARCHAR(20) | ❌ no en response | 🟡 Existe en modelo |
| [commit_hash](file:///d:/Proyectos/INI_Code-Agent/src/core/analyzers/pipeline.py#231-246) | VARCHAR(40) | ❌ no en response archivos | 🟡 Existe en modelo |
| `escaneado_en` | TIMESTAMP | ❌ no en response | 🟡 Existe en modelo |
| `activo` | BOOLEAN | ❌ | 🟡 Default true |

---

## 2. `unidades_logicas`

| Columna A-ONE | Tipo | En respuesta actual | Estado |
|---|---|---|---|
| [id](file:///d:/Proyectos/INI_Code-Agent/src/models/domain.py#83-103) | UUID_V7 | ❌ | 🔴 Falta |
| `archivo_id` | UUID_V7 | ❌ (usamos `archivo` como nombre) | 🔴 Falta — hoy es nombre, no UUID |
| `parent_id` | UUID_V7 | ⚠️ `parent` (nombre limpio, no UUID) | 🟡 Existe pero como nombre |
| `activo_id` | UUID_V7 | ❌ no en response | 🟡 Existe en modelo |
| `aplicacion_id` | UUID_V7 | ❌ no en response | 🟡 Existe en modelo |
| `nombre` | VARCHAR(255) | ✅ `nombre` | ✅ OK |
| `tipo` | VARCHAR(20) | ✅ `tipo` | ✅ OK |
| `linea_inicio` | INTEGER | ✅ `linea_inicio` | ✅ OK |
| `linea_fin` | INTEGER | ✅ `linea_fin` | ✅ OK |
| `complejidad` | INTEGER | ✅ `complejidad` | ✅ OK |
| `lineas_codigo` | INTEGER | ✅ `lineas_codigo` | ✅ OK |
| `accede_bd` | BOOLEAN | ✅ `accede_bd` | ✅ OK |
| `llamadas_externas` | INTEGER | ❌ no en response | 🔴 Falta (existe en modelo) |
| `docstring` | BOOLEAN | ✅ `docstring` | ✅ OK |
| `resumen` | TEXT | ❌ no en response | 🔴 Falta (se genera en enrich) |
| `metadata` | TEXT(JSON) | ⚠️ parcial (`capa`, `overall_score`, `risk_level`) | 🟡 Falta: `compliance`, [imports](file:///d:/Proyectos/INI_Code-Agent/src/core/analyzers/logical_unit_extractor.py#270-275), `decorators`, `parameters`, `return_type`, `reglas_negocio` |
| `activo` | BOOLEAN | ❌ | 🟡 Default true |

---

## 3. `escaneos`

| Columna A-ONE | Tipo | En respuesta actual | Estado |
|---|---|---|---|
| [id](file:///d:/Proyectos/INI_Code-Agent/src/models/domain.py#83-103) | UUID_V7 | ❌ | 🔴 Falta |
| `activo_id` | UUID_V7 | ❌ no en response | 🟡 Existe en request |
| `aplicacion_id` | UUID_V7 | ❌ no en response | 🟡 Existe en request |
| `build_number` | VARCHAR(20) | ❌ | 🟡 |
| [commit_hash](file:///d:/Proyectos/INI_Code-Agent/src/core/analyzers/pipeline.py#231-246) | VARCHAR(40) | ✅ [commit_hash](file:///d:/Proyectos/INI_Code-Agent/src/core/analyzers/pipeline.py#231-246) | ✅ OK |
| `escaneado_en` | TIMESTAMP | ❌ | 🔴 Falta |
| `generado_por` | VARCHAR(100) | ❌ | 🔴 Falta |
| `score_general` | DECIMAL | ✅ `score_general` | ✅ OK |
| `nivel_riesgo` | VARCHAR(10) | ✅ `nivel_riesgo` | ✅ OK |
| `archivos_total` | INTEGER | ✅ `archivos_total` | ✅ OK |
| `funciones_total` | INTEGER | ✅ `funciones_total` | ✅ OK |
| `clases_total` | INTEGER | ✅ `clases_total` | ✅ OK |
| `dominios_negocio` | TEXT(JSON) | ❌ | 🔴 Falta |
| `metricas` | TEXT(JSON) | ⚠️ parcial (`avg_complexity`, `max_complexity`, `languages`) | 🟡 Falta `loc_total`, `avg_score` como JSON separado |
| `arquitectura` | TEXT(JSON) | ⚠️ parcial (`capas`) | 🟡 Falta `multi_layer_count` |
| `seguridad` | TEXT(JSON) | ❌ (Semgrep genera pero no se incluye en [_build_results](file:///d:/Proyectos/INI_Code-Agent/src/api/routes/scan.py#41-139)) | 🔴 Falta |
| `rendimiento` | TEXT(JSON) | ❌ | 🔴 Falta |
| `negocio` | TEXT(JSON) | ❌ | 🔴 Falta |
| `cumplimiento` | TEXT(JSON) | ❌ | 🔴 Falta |

---

## Resumen de Gaps

| Prioridad | Gap | Impacto |
|---|---|---|
| 🔴 **Alto** | `resumen` no se devuelve en archivos ni unidades | El LLM lo genera pero [_build_results()](file:///d:/Proyectos/INI_Code-Agent/src/api/routes/scan.py#41-139) no lo incluye |
| 🔴 **Alto** | `metadata` completa no se devuelve en archivos ni unidades | Faltan [imports](file:///d:/Proyectos/INI_Code-Agent/src/core/analyzers/logical_unit_extractor.py#270-275), `decorators`, `parameters`, `reglas_negocio` |
| 🔴 **Alto** | `seguridad` del escaneo no se llena | Semgrep lo genera pero no se conecta al response |
| 🔴 **Alto** | `negocio` y `dominios_negocio` del escaneo vacíos | Las reglas de negocio del enrich no se agregan al escaneo |
| 🟡 **Medio** | `escaneado_en`, `generado_por` no en response escaneo | Facil de agregar |
| 🟡 **Medio** | `llamadas_externas` falta en response unidades | Existe en modelo, no en [_build_results](file:///d:/Proyectos/INI_Code-Agent/src/api/routes/scan.py#41-139) |
| 🟡 **Bajo** | `cumplimiento` y `rendimiento` vacíos | Requiere lógica adicional de cálculo |

> [!IMPORTANT]
> Los gaps 🔴 son datos que **ya generamos** en el pipeline pero simplemente **no incluimos** en [_build_results()](file:///d:/Proyectos/INI_Code-Agent/src/api/routes/scan.py#41-139). La mayoría se resuelve solo agregando campos al dict de la respuesta — sin cambiar lógica de negocio.
