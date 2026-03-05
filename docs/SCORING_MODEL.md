# Modelo de Scoring y Risk — doc-as-codePRO v3.0

Documento técnico que explica cómo el pipeline de Fase 1 calcula el `overall_score` y el `risk_level` de cada unidad lógica (función o clase).

Fuente de verdad: `src/core/analyzers/logical_unit_extractor.py`

---

## 1. Overall Score (0 – 100)

El score representa la **mantenibilidad** de una unidad lógica. Un score alto (cercano a 100) indica código limpio, simple y bien separado. Un score bajo indica deuda técnica.

### Fórmula

```
overall_score = (atomicity × 0.4 + transparency × 0.4 + complexity_score × 0.2) × 100
```

Tres componentes con pesos distintos:

---

### 1.1 Atomicity — peso 40%

Mide si la función es **pequeña y simple** (principio de responsabilidad única).

```
atomicity = 1.0
  si loc > 30       → -0.3   (función demasiado larga)
  si complexity > 10 → -0.3  (demasiadas ramas de decisión)
mínimo: 0.0
```

| Condición | Penalización | Significado |
|---|---|---|
| LOC > 30 | -0.30 | Función larga, difícil de leer de un vistazo |
| Complejidad > 10 | -0.30 | Demasiados caminos de ejecución |
| Ambas | -0.60 → 0.40 | Función larga Y compleja |
| Ninguna | 0.00 → 1.00 | Función atómica ideal |

> **Nota Java**: el LOC se calcula como `total_lines_archivo / total_funciones`. Es una aproximación — Java no tiene `func_complexity` por método (gap conocido, pendiente Fase 2).

---

### 1.2 Transparency — peso 40%

Mide si la función **mezcla lógica de negocio con acceso a infraestructura** (violación de separación de capas).

```
transparency = 1.0
  si tiene database_calls              → -0.4  (accede directamente a BD)
  si tiene imports de infra detectados → -0.3  (acoplada a infraestructura)
mínimo: 0.0
```

Imports de infraestructura detectados:

| Categoría | Ejemplos |
|---|---|
| Python BD | `psycopg2`, `sqlalchemy`, `pymongo`, `redis` |
| Python AWS | `boto3`, `dynamodb`, `s3`, `sqs`, `sns` |
| Java BD | `java.sql`, `javax.sql`, `org.hibernate` |
| Java JPA | `javax.persistence`, `jakarta.persistence` |
| Java AWS | `com.amazonaws`, `software.amazon` |
| Java Spring Data | `org.springframework.data` |

| Condición | Penalización | Significado |
|---|---|---|
| Tiene `database_calls` | -0.40 | Llama directamente a BD (execute, query, find…) |
| Tiene imports de infra | -0.30 | Importa librerías de infraestructura |
| Ambas | -0.70 → 0.30 | Acoplamiento total a infraestructura |
| Ninguna | 0.00 → 1.00 | Lógica pura de dominio |

---

### 1.3 Complexity Score — peso 20%

Inverso de la **complejidad ciclomática**. A mayor complejidad, menor score.

```
complexity_score = 1.0 / max(complexity, 1)
```

| Complejidad | Complexity Score |
|---|---|
| 1 (sin ramas) | 1.00 |
| 5 | 0.20 |
| 10 | 0.10 |
| 20 | 0.05 |

La complejidad ciclomática cuenta: `if`, `while`, `for`, `except/catch`, `switch`, operadores booleanos (`and`/`or`).

---

### Ejemplos de score

| Función | LOC | Complexity | DB calls | Infra imports | Score |
|---|---|---|---|---|---|
| Getter simple | 3 | 1 | No | No | **100.0** |
| Validación pura | 20 | 5 | No | No | **84.0** |
| Servicio con BD | 25 | 3 | Sí | Sí | **42.86** |
| God method | 80 | 20 | Sí | Sí | **18.0** |

---

## 2. Risk Level

El `risk_level` combina **complejidad ciclomática** y **overall_score** para clasificar el riesgo de mantenimiento.

### Fórmula (v2 — actualizada)

```python
def _calc_risk(complexity: int, score: float) -> RiskLevel:
    if complexity > 15 or score < 50:   return HIGH
    if complexity >= 10 or score < 70:  return MEDIUM
    return LOW
```

### Tabla de clasificación

| Risk | Condición | Significado |
|---|---|---|
| **HIGH** | complejidad > 15 ó score < 50 | Requiere refactor prioritario |
| **MEDIUM** | complejidad ≥ 10 ó score < 70 | Requiere atención en próximo sprint |
| **LOW** | resto | Código saludable |

### Por qué se usa score Y complejidad

La versión anterior usaba solo complejidad ciclomática. El problema: una función puede ser simple en flujo (pocos `if`) pero estar fuertemente acoplada a infraestructura, resultando en score bajo. Eso es deuda técnica real que el risk debe reflejar.

Ejemplos del impacto:

| Función | Complexity | Score | Risk v1 | Risk v2 |
|---|---|---|---|---|
| `_calculate_user_baseline` | 3 | 42.86 | LOW ❌ | **HIGH** ✅ |
| `getKeyMethodMap` (Java) | 18 | 44.06 | HIGH ✅ | **HIGH** ✅ |
| `getName` (getter) | 1 | 100.0 | LOW ✅ | **LOW** ✅ |

---

## 3. Score de Clase

El score de una clase se calcula como el **promedio de los scores de sus funciones hijas**. El risk de la clase usa la **complejidad máxima** entre sus funciones junto con el score promedio.

```python
clase.overall_score = promedio(scores de funciones hijas)
clase.risk_level    = _calc_risk(max(complexity de hijas), clase.overall_score)
```

---

## 4. Clasificación de Capa Arquitectónica

Cada unidad se clasifica en una capa según sus imports:

| Capa | Criterio |
|---|---|
| `adaptador` | Tiene imports de framework web (FastAPI, Flask, Struts, Servlet) pero NO de infra |
| `infraestructura` | Tiene imports de BD, ORM, AWS, o framework web + infra |
| `dominio` | Sin imports de adaptador ni infraestructura |

---

## 5. Umbrales de referencia rápida

| Score | Interpretación |
|---|---|
| 90 – 100 | Excelente — código limpio y atómico |
| 70 – 89 | Bueno — alguna penalización menor |
| 50 – 69 | Regular — deuda técnica presente |
| < 50 | Crítico — refactor recomendado |
