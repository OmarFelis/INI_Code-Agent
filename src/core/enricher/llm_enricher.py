import os
import json
import asyncio
import boto3
import structlog
from typing import List, Dict

logger = structlog.get_logger()

# Configuración AWS Bedrock
REGION = "us-east-1"
# Modelo recomendado para costos bajos y velocidad
MODEL_ID = "anthropic.claude-3-haiku-20240307-v1:0" 
PROFILE_NAME = "AmazonBedrockLimitedAccess-460896925620"

PROMPT_TACTICO = """
Eres un Arquitecto de Software Experto especializado en ingeniería inversa. 
Tu tarea es leer código fuente y extraer (1) un resumen funcional conciso y (2) las reglas de negocio explícitas.

<esquema_clase>
{esquema_clase}
</esquema_clase>

Analiza la siguiente función concreta de este componente ({nombre_funcion}):
<codigo_funcion>
{codigo_original}
</codigo_funcion>

INSTRUCCIONES: Extrae reglas de negocio (condicionales) y un resumen funcional estructurado. Para cada regla, incluye la explicación y el fragmento de código (snippet) exacto que evalúa la condición.
Devuelve EXACTAMENTE este formato JSON purista sin bloques de markdown:
{{
  "resumen_funcional": "string en español",
  "modifica_estado": boolean,
  "reglas_de_negocio": [
    {{
      "descripcion": "explicación de la regla de negocio",
      "codigo_relacionado": "if (edad < 18) {{ throw Error... }}"
    }}
  ]
}}
"""

def get_bedrock_client():
    """Inicializa la sesión de Boto3 con las credenciales mapeadas del perfil."""
    try:
        session = boto3.Session(profile_name=PROFILE_NAME)
        return session.client('bedrock-runtime', region_name=REGION)
    except Exception as e:
        logger.error("error_initializing_bedrock", error=str(e), profile=PROFILE_NAME)
        raise

async def bedrock_llm_call(prompt: str, function_name: str) -> dict:
    """
    Ejecuta una llamada asíncrona a Claude en AWS Bedrock
    usando asyncio.to_thread para no bloquear el Worker de FastAPI.
    """
    def _invoke():
        client = get_bedrock_client()
        payload = {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 512,
            "temperature": 0.1, 
            "messages": [
                {
                    "role": "user",
                    "content": prompt
                }
            ]
        }
        
        response = client.invoke_model(
            modelId=MODEL_ID,
            body=json.dumps(payload),
            contentType="application/json",
            accept="application/json"
        )
        body = json.loads(response['body'].read().decode('utf-8'))
        response_text = body['content'][0]['text']
        
        # Limpieza robusta del JSON frente a alucinaciones menores
        if "```json" in response_text:
            response_text = response_text.split("```json")[1].split("```")[0].strip()
        elif "```" in response_text:
            response_text = response_text.split("```")[1].strip()
            
        return json.loads(response_text)

    try:
        return await asyncio.to_thread(_invoke)
    except Exception as e:
        logger.error("bedrock_call_failed", function=function_name, error=str(e))
        return {
             "error": str(e),
             "resumen_funcional": f"Falló Bedrock para {function_name}",
             "modifica_estado": False,
             "reglas_de_negocio": []
        }

async def analyze_functions_batch(funciones: List[Dict]) -> List[Dict]:
    """
    Toma una lista de diccionarios de funciones y lanza el prompt para 
    cada uno de forma concurrente, devolviendo los resultados procesados.
    """
    tareas = []
    
    # Preparamos todos los llamados a la API de LLM (Orquestación asíncrona)
    for func in funciones:
        prompt = PROMPT_TACTICO.format(
            nombre_funcion=func.get('nombre_funcion'),
            esquema_clase=func.get('componente', 'Desconocido'),
            codigo_original=func.get('codigo_original', 'Sin código')
        )
        tareas.append(bedrock_llm_call(prompt, func.get('nombre_funcion')))
        
    logger.info("llm_batch_started", size=len(tareas))
    # Ejecuta todo al mismo tiempo en paralelo, resolviendo los Futures de Bedrock
    resultados_ia = await asyncio.gather(*tareas, return_exceptions=True)
    logger.info("llm_batch_completed")

    resultados_finales = []
    
    # Acoplamos el input con el output y mapeamos el Pydantic format indirectamente
    for idx, func in enumerate(funciones):
        res_ia = resultados_ia[idx]
        
        enriched = {
            "nombre_funcion": func.get('nombre_funcion'),
            "componente": func.get('componente'),
            "archivo": func.get('archivo'),
            "analisis_ia": {}
        }
        
        if isinstance(res_ia, Exception):
             enriched['analisis_ia'] = {'error': str(res_ia)}
        else:
             enriched['analisis_ia'] = res_ia
             
        resultados_finales.append(enriched)

    return resultados_finales
