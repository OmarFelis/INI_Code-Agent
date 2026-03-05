# Análisis Técnico — {microservice_name}

> Generado por **doc-as-codePRO v3.0**
> Fuente: `quality_audits` PostgreSQL — siempre refleja el último análisis ejecutado.
> A diferencia de documentos estáticos, este reporte se regenera desde datos estructurados
> y es comparable entre builds, entornos y microservicios.

---

## Información de Versión

| Campo | Valor |
|-------|-------|
| Microservicio | `{entity_name}` |
| Lenguaje principal | `{language}` |
| Entorno de ejecución | `{runtime_env}` |
| Equipo responsable | `{description.owner_team}` |
| Sensibilidad de datos | `{description.data_sensitivity}` |
| Último análisis | `{created_at}` |
| Commit analizado | `{metrics.commit_hash}` |
| Build | `#{metrics.build_number}` |
| ID en quality_audits | `{id}` |

---

## Resumen Ejecutivo

| Métrica | Valor |
|---------|-------|
| Overall Score | **{overall_score} / 100** |
| Risk Level | **{risk_level}** |
| Archivos analizados | `{metrics.total_files}` |
| Líneas de código | `{metrics.total_lines}` |
| Unidades lógicas | calculado: `COUNT(*) WHERE parent_id={id}` |
| Unidades HIGH risk | calculado: `COUNT(*) WHERE parent_id={id} AND risk_level='HIGH'` |
| Unidades MULTICAPA | calculado: `COUNT(*) WHERE compliance->>'has_multi_layer_coupling'='true'` |
| Reglas de negocio | `{metrics.business_rules_count}` |

### Interpretación del Score

```
0 ────────────────────────────────────── 100
         40        70
[  HIGH  ][  MEDIUM  ][        LOW        ]
              ▲
         {overall_score}  ← {microservice_name}
```

> El score mide calidad estructural del código: atomicidad de funciones (40%),
> transparencia de dependencias (40%) e inverso de complejidad ciclomática (20%).

---

## Distribución por Capa Arquitectónica

| Capa | Unidades | % | Descripción |
|------|----------|---|-------------|
| DOMINIO `[DOM]` | {dom_count} | {dom_pct}% | Lógica de negocio pura, sin dependencias de infraestructura |
| INFRAESTRUCTURA `[INF]` | {inf_count} | {inf_pct}% | Acceso a BD, servicios externos, AWS |
| ADAPTADOR `[ADP]` | {adp_count} | {adp_pct}% | Endpoints HTTP, handlers, controllers |

---

## Propósito del Microservicio

> *Campo `description` JSONB — generado por LLM (Bedrock Claude 3.5 Sonnet) en Fase 2 Paso 8*

**Qué hace:** `{description.summary}`

**Por qué existe:** `{description.purpose}`

**Valor de negocio:** `{description.business_value}`

**Equipo responsable:** `{description.owner_team}`

**Sensibilidad de datos:** `{description.data_sensitivity}` *(ej: HIGH PCI-DSS, MEDIUM, LOW)*

---

## Dependencias Externas

> *Campo `external_relations` JSONB — detectado por análisis estático + enriquecido por LLM*

### Servicios que llaman a este microservicio (inbound)

| Origen | Protocolo | Tipo |
|--------|-----------|------|
| `{external_relations.inbound[].source}` | `{...protocol}` | `{...type}` |

### Servicios que este microservicio llama (outbound)

| Destino | Tipo |
|---------|------|
| `{external_relations.outbound[].target}` | `{...type}` |

### Almacenamiento de datos

| Recurso | Tipo |
|---------|------|
| `{external_relations.data_storage[].resource}` | `{...type}` |

### Eventos publicados

| Topic | Bus |
|-------|-----|
| `{external_relations.events_published[].topic}` | `{...bus}` |

---

## Unidades Lógicas — Detalle

> Ordenadas por risk_level DESC, overall_score ASC (las más críticas primero)

### Unidades HIGH Risk

| Función | Capa | Score | Complejidad | LOC | MULTICAPA |
|---------|------|-------|-------------|-----|-----------|
{high_risk_table}

### Unidades MEDIUM Risk

| Función | Capa | Score | Complejidad | LOC |
|---------|------|-------|-------------|-----|
{medium_risk_table}

### Unidades LOW Risk (resumen)

{low_risk_count} unidades con score promedio de {low_risk_avg_score}.
Ver detalle completo en `quality_audits` con `parent_id = {microservice_id}`.

---

## Reglas de Negocio Identificadas

> *Extraídas por LLM solo de unidades capa DOMINIO*
> *Trazabilidad completa: cada regla vinculada a su función origen*

{business_rules_section}

---

## Hallazgos de Calidad

### Unidades MULTICAPA detectadas

Las siguientes funciones mezclan responsabilidades de más de una capa arquitectónica.
Son candidatas prioritarias a refactor:

{multicapa_section}

### Compliance checklist

> *Campo `compliance` JSONB — calculado por análisis estático*

| Criterio | Cumple | Unidades que fallan |
|----------|--------|---------------------|
| LOC por función ≤ 30 | `compliance.loc_ok` | calculado |
| Complejidad ≤ 10 | `compliance.complexity_ok` | calculado |
| Sin acoplamiento multicapa | `!compliance.has_multi_layer_coupling` | calculado |

---

## Recomendaciones

> Generadas a partir de los hallazgos de `compliance` y `risk_level`

{recommendations_section}

---

## Comparación con análisis anterior

> *Disponible cuando se ejecuta `POST /api/v1/compare` — Fase 2 Paso 9*

| Métrica | Análisis anterior | Este análisis | Delta |
|---------|------------------|---------------|-------|
| Overall Score | {prev_score} | {overall_score} | {score_delta} |
| Unidades HIGH | {prev_high} | {high_risk_units} | {high_delta} |
| Unidades nuevas | — | {new_units} | — |
| Unidades eliminadas | — | {removed_units} | — |

---

## Metadata técnica

> Registro completo del microservicio en `quality_audits`

```json
{
  "id": "{id}",
  "entity_name": "{entity_name}",
  "entity_type": "MICROSERVICE",
  "language": "{language}",
  "runtime_env": "{runtime_env}",
  "risk_level": "{risk_level}",
  "overall_score": {overall_score},
  "description": {
    "summary": "{description.summary}",
    "purpose": "{description.purpose}",
    "business_value": "{description.business_value}",
    "owner_team": "{description.owner_team}",
    "data_sensitivity": "{description.data_sensitivity}"
  },
  "external_relations": {
    "inbound": [{"source": "...", "protocol": "...", "type": "..."}],
    "outbound": [{"target": "...", "type": "..."}],
    "data_storage": [{"resource": "...", "type": "..."}],
    "events_published": [{"topic": "...", "bus": "..."}]
  },
  "metrics": {
    "total_files": {metrics.total_files},
    "total_lines": {metrics.total_lines},
    "languages": {metrics.languages},
    "commit_hash": "{metrics.commit_hash}",
    "build_number": "{metrics.build_number}",
    "business_rules_count": {metrics.business_rules_count}
  },
  "compliance": {
    "loc_ok": true,
    "complexity_ok": true,
    "has_multi_layer_coupling": false
  },
  "created_at": "{created_at}"
}
```

---

*Generado por doc-as-codePRO v3.0 — Alignet Ecosistema de Pagos Digitales*
*Fuente de verdad: PostgreSQL `quality_audits` — no editar manualmente*
