# ⏱️ Backlog de Registro de Tiempos — Code-Agent V1.0

Este documento sirve para registrar el tiempo estimado y el tiempo real (en horas) invertido en la implementación de cada fase del proyecto Code-Agent, basándose en el Plan de Implementación V1.0.

## Resumen de Tiempos por Fase

| Fase | Descripción | Tiempo Estimado (h) | Tiempo Real (h) | Estado |
|---|---|---|---|---|
| **Fase 0** | Servicio base y API REST | | | ⏳ Pendiente |
| **Fase 1** | Parseo, Clasificación y Persistencia | | | ⏳ Pendiente |
| **Fase 2** | Enriquecimiento con IA | | | ⏳ Pendiente |
| **Fase 3** | Integración con A-ONE y Grafo | | | ⏳ Pendiente |
| **Fase 4** | Cobertura Multi-Repositorio | | | ⏳ Pendiente |
| **Total** | | **0** | **0** | |

---

## Detalle de Tareas

### FASE 0 — Servicio base y API REST
| Tarea | Asignado a | Fecha de Inicio | Fecha de Fin | Tiempo Estimado (h) | Tiempo Real (h) | Estado | Comentarios |
|---|---|---|---|---|---|---|---|
| Inicialización de FastAPI (Rutas, Schemas) | | | | | | To Do | |
| Configuración BD local y Docker Compose | | | | | | To Do | |
| Setup logging estructural y middlewares | | | | | | To Do | |
| Endpoint genérico POST /scan y GET /scan/{id} | | | | | | To Do | |

### FASE 1 — Parseo, Clasificación y Persistencia
| Tarea | Asignado a | Fecha de Inicio | Fecha de Fin | Tiempo Estimado (h) | Tiempo Real (h) | Estado | Comentarios |
|---|---|---|---|---|---|---|---|
| Script extractor AST (Jerarquía lógica) | | | | | | To Do | |
| Implementar pipeline generador de archivos | | | | | | To Do | |
| Lógica de Scoring Automático y niveladores | | | | | | To Do | |
| Clientes HTTP para DB y endpoints A-ONE | | | | | | To Do | |

### FASE 2 — Enriquecimiento con IA
| Tarea | Asignado a | Fecha de Inicio | Fecha de Fin | Tiempo Estimado (h) | Tiempo Real (h) | Estado | Comentarios |
|---|---|---|---|---|---|---|---|
| Conexión con AWS Bedrock (Haiku / Sonnet) | | | | | | To Do | |
| Prompts de Resumen y Reglas Negocio | | | | | | To Do | |
| Infraestructura y lógica de Cache (AWS / Local) | | | | | | To Do | |
| Integrar Semgrep (Pipelines estáticos y JSON) | | | | | | To Do | |

### FASE 3 — Integración con A-ONE y Grafo
| Tarea | Asignado a | Fecha de Inicio | Fecha de Fin | Tiempo Estimado (h) | Tiempo Real (h) | Estado | Comentarios |
|---|---|---|---|---|---|---|---|
| Implementación lógica del Grafo DTOs | | | | | | To Do | |
| Vistas materializadas de reportes o tests | | | | | | To Do | |

### FASE 4 — Cobertura Multi-Repositorio
| Tarea | Asignado a | Fecha de Inicio | Fecha de Fin | Tiempo Estimado (h) | Tiempo Real (h) | Estado | Comentarios |
|---|---|---|---|---|---|---|---|
| Adaptadores clonados de Git / SCM | | | | | | To Do | |
| API Batch requests múltiples | | | | | | To Do | |
| Pruebas masivas con orquestador real | | | | | | To Do | |

---
*Instrucciones:*
- *Añade las horas estimadas (Tiempo Estimado) previo a tomar la tarea.*
- *Actualiza la columna "Tiempo Real (h)" al finalizar la tarea y ajusta el estado a "Done".*
- *Suma frecuentemente los tiempos a la tabla de 'Resumen de Tiempos por Fase'.*
