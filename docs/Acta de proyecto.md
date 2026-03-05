Tema Principal:

El objetivo central es automatizar y estructurar el análisis de código de microservicios utilizando un agente de Inteligencia Artificial (llamado "CodAgent" o "Agente 14"). Esto busca reemplazar los análisis manuales extensos con un proceso eficiente que genere documentación, diagnósticos de calidad y métricas, todo almacenado en una base de datos centralizada para mejorar la mantenibilidad y el entendimiento del código.

Funcionalidades Clave del Agente (Fase Inicial - Offline):

Resumen Estructurado: Generar resúmenes, descripciones generales y propósitos del código en campos JSON dentro de una base de datos. Esto incluirá tanto lo que el agente puede inferir como la capacidad de edición humana.

Separación de Unidades Lógicas: Identificar y separar las unidades lógicas dentro de un microservicio (entradas, reglas, funciones, ciclos, salidas), modelando cada una como un activo separado con su propia descripción y propósito.

Diagnóstico de Calidad del Código: Realizar un "checklist de salud" con puntuaciones automatizadas sobre diversos aspectos:

Atomicidad: Determinar si una unidad realiza una única función.

Transparencia: Evaluar si es una función pura.

Complejidad: Medir la linealidad de la lectura y los niveles de anidamiento.

Métricas: Analizar la longitud de las funciones y el nivel de indentación.

Dependencias: Identificar el número de servicios externos utilizados.

Consideraciones Específicas del Lenguaje: Aplicar estándares para Python (ej. type hinting, estilo estándar) y Java (ej. uso de interfaces).

Estructura de Caja Negra: Validar esquemas de entrada/salida e identificar procesos de negocio.

Mantenibilidad: Responder preguntas clave sobre la facilidad de mantenimiento.

Evaluación de Riesgos y Puntuación: El agente asignará un nivel de riesgo (alto, medio, bajo) y una puntuación general al código analizado, permitiendo priorizar la revisión por parte del equipo técnico.

Relaciones Externas: Identificar las invocaciones a componentes de Amazon u otros servicios externos para construir un mapa de dependencias.

Integración y Estructura de Datos:

Base de Datos SQL: Toda la información generada se registrará en una base de datos SQL (PostgreSQL), utilizando campos JSON para almacenar detalles estructurados.

Separación de Activos: Se planea separar los activos de infraestructura (AWS) de los activos de código, ya que estos últimos contienen información más crítica y detallada.

Modelo de Datos: Stefano se encargará de diseñar la estructura de las tablas para alojar microservicios y unidades lógicas, incluyendo campos para ID, parent (aplicación/microservicio), nombre, tipo, runtime, lenguaje, nivel de riesgo, score, descripción detallada, propósito, propietario, equipo y sensibilidad de datos.

Métricas Cuantitativas: Se buscará capturar métricas como líneas de código, endpoints, complejidad ciclomática y cobertura de pruebas.

Flujo de Trabajo y Roles:

Definición del Diagnóstico: Se dedicarán aproximadamente 2-4 horas para definir qué información extraerá el agente y qué diagnósticos realizará, con la participación de Omar, Root y la opinión del hablante.

Validación de Tecnología: El documento de diagnóstico se compartirá con el equipo de tecnología, dándoles 48 horas para proporcionar comentarios y validación.

Preparación de la Base de Datos: Stefano preparará la estructura de datos en paralelo.

Cronograma: El mapeo de aplicaciones clave (orquestador, transaction key PC, ACC) está proyectado para el 14-15 de marzo.

Responsabilidades: El equipo desarrollará el diagnóstico y el modelo de datos, mientras que el equipo de tecnología validará y proporcionará acceso a los repositorios de código (Bitbucket).

Visión a Largo Plazo y Evolución:

Análisis de Impacto: Vincular las reglas de negocio de los "features" a microservicios y unidades lógicas específicas para un análisis de impacto preciso ante los cambios.

Arquitectura Viva: Transformar los diagramas de arquitectura en representaciones interactivas y dinámicas, donde se pueda profundizar desde una vista de alto nivel hasta el detalle de cada función y su diagnóstico, eliminando la necesidad de documentación manual externa como Confluence.

Generación y Verificación de Código Asistida por Agentes: Utilizar agentes para generar código siguiendo estándares y estructuras predefinidas, con verificación automática durante el despliegue.

Versionamiento y Control de Cambios: Implementar un sistema de versionamiento para comparar el estado del código en producción, testing y desarrollo.

Mantenimiento Continuo: Establecer un proceso para la actualización y el mantenimiento del análisis del agente a medida que el código evoluciona.

Ampliación del Alcance: Inicialmente, el enfoque es en el código de microservicios (Lambdas y ECS). En el futuro, se extenderá al análisis de código frontend (ej. componentes, hooks) para asegurar su estructura y calidad.

Consideraciones y Desafíos:

El agente debe poder analizar código en Bitbucket (Lambdas, ECS).

Abordar microservicios "monolíticos" (ej. un ECS con muchas funciones) que requieren refactorización.

La necesidad de un "Agent Core" que permita a perfiles de negocio utilizar los agentes de IA, complementando los perfiles técnicos.

La importancia de definir con claridad lo que el agente analizará y cómo lo guardará, para que los resultados sean útiles y comprensibles para el equipo técnico.
