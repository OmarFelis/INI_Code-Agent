import json
import asyncio
import os
import aiohttp

import boto3

# --- CONFIGURACIÓN AWS BEDROCK ---
REGION = "us-east-1"
MODEL_ID = "anthropic.claude-3-haiku-20240307-v1:0" # Modelo rápido y económico
PROFILE_NAME = "AmazonBedrockLimitedAccess-460896925620"

def get_bedrock_client():
    session = boto3.Session(profile_name=PROFILE_NAME)
    return session.client('bedrock-runtime', region_name=REGION)

async def bedrock_llm_call(prompt: str, function_name: str) -> dict:
    """
    Ejecuta una llamada asíncrona real a Claude 3 Haiku en AWS Bedrock
    usando asyncio.to_thread para no bloquear el Event Loop con boto3 (que es síncrono).
    """
    def _invoke():
        client = get_bedrock_client()
        payload = {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 512,
            "temperature": 0.1, # Muy baja variabilidad para que respete el JSON
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
        
        # Limpiar posible basura fuera del JSON que el LLM pueda agregar (markdown)
        if "```json" in response_text:
            response_text = response_text.split("```json")[1].split("```")[0].strip()
        elif "```" in response_text:
            response_text = response_text.split("```")[1].strip()
            
        return json.loads(response_text)

    try:
        # Correr la función síncrona de boto3 en un thread pool asíncrono
        return await asyncio.to_thread(_invoke)
    except Exception as e:
        print(f"BOTO3 ERROR DETAILED: {e}")
        return {
             "error": str(e),
             "resumen_funcional": f"Falló Bedrock para {function_name}",
             "modifica_estado": False,
             "reglas_de_negocio": []
        }

# --- PROMPTS ---
PROMPT_TACTICO = """
Eres un Arquitecto de Software Experto. Analiza la siguiente función: {nombre_funcion}

<esquema_clase>
{esquema_clase}
</esquema_clase>

INSTRUCCIONES: Extrae reglas de negocio (condicionales) y un resumen funcional.
Devuelve EXACTAMENTE este formato JSON:
{{
  "resumen_funcional": "string en español",
  "modifica_estado": boolean,
  "reglas_de_negocio": ["regla 1", "regla 2"]
}}
"""

# --- ESTRATEGIA 1: FILTRADO INTELIGENTE ---
def filtrar_unidades_analizables(unidades_logicas: list) -> list:
    """Filtra y devuelve solo las funciones que valen la pena analizar."""
    analizables = []
    
    # Preconstruir mapa de padres para saber de qué clase vienen
    mapa_padres = {u['id']: u for u in unidades_logicas if u['tipo'] == 'CLASE' and 'id' in u}

    for u in unidades_logicas:
        if u['tipo'] != 'FUNCION':
            continue
            
        # Estrategia 1: Filtrar getters/setters y funciones muy chicas
        nombre = u.get('nombre', '')
        if nombre.startswith('get') or nombre.startswith('set'):
            continue
            
        loc = u.get('lineas_codigo', 0)
        if loc < 5:
            continue
            
        # Priorizar Dominio o Alta Complejidad
        capa = u.get('capa', 'Desconocida')
        complejidad = u.get('complejidad', 0)
        
        if capa == 'Dominio' or complejidad > 8:
            # Estrategia 2: Construir el Esqueleto
            padre = mapa_padres.get(u.get('parent_id'))
            esquema = padre.get('nombre', 'ClaseIndependiente') if padre else 'Standalone'
            
            u['_meta_analisis'] = {
                'esquema_padre': esquema
            }
            analizables.append(u)
            
    return analizables

# --- ESTRATEGIA 4: ORQUESTACIÓN ASÍNCRONA BATCH ---
async def analizar_lote_concurrente(funciones_batch: list) -> list:
    tareas = []
    for func in funciones_batch:
        prompt = PROMPT_TACTICO.format(
            nombre_funcion=func['nombre'],
            esquema_clase=func['_meta_analisis']['esquema_padre']
        )
        # LLamada asíncrona concurrente a Bedrock
        tareas.append(bedrock_llm_call(prompt, func['nombre']))
        
    # Ejecuta todo al mismo tiempo y espera que terminen
    resultados = await asyncio.gather(*tareas, return_exceptions=True)
    return resultados

async def run_analysis(file_path: str):
    print("--- Iniciando Estrategia Agentic (Prototipo V1) ---")
    
    import re
    with open(file_path, 'r', encoding='utf-8') as f:
        raw_data = f.read()
        
    # Limpiamos el formato git diff si existe (++ en el json)
    if '@@' in raw_data or raw_data.startswith('+'):
        # Quita la metadata inicial
        raw_data = re.sub(r'^@@.*?@@\n', '', raw_data)
        # Quita todos los '+' del principio de línea
        raw_data = re.sub(r'^\+', '', raw_data, flags=re.MULTILINE)
        
    data = json.loads(raw_data)
        
    todas_unidades = data['results'].get('unidades_logicas', [])
    todos_archivos = data['results'].get('archivos_fuente', [])
    mapa_archivos = {f['nombre']: f['ruta_archivo'] for f in todos_archivos}
    print(f"--- Total unidades encontradas en JSON: {len(todas_unidades)}")
    
    # 1. Aplicamos Filtro Inteligente (Estrategia 1)
    filtradas = filtrar_unidades_analizables(todas_unidades)
    print(f"--- Unidades que pasaron el filtro (Dominio/Complejas, >5 LOC, no get/set): {len(filtradas)}")
    
    if not filtradas:
        print("No hay funciones para analizar con estos criterios.")
        return
        
    # Tomamos solo las primeras 10 para no saturar el prototipo
    batch_prueba = filtradas[:10]
    print(f"--- Ejecutando lote de {len(batch_prueba)} funciones vía LLM (Asyncio)...")
    
    # 4. Análisis Concurrente en Bedrock (Estrategia 4)
    resultados_ia = await analizar_lote_concurrente(batch_prueba)
        
    # Mostrar resultados
    print("\n--- Resultados de la IA ---")
    resultados_finales = []
    
    REPO_BASE_PATH = "C:/FLOTAS - Assessments/flotas-mod_empresa"

    for idx, func in enumerate(batch_prueba):
        nombre = func['nombre']
        res_ia = resultados_ia[idx]
        
        # Extraer el codigo original
        codigo_original = "Código no encontrado"
        archivo_nombre = func.get('archivo')
        ruta_relativa = mapa_archivos.get(archivo_nombre)
        if ruta_relativa:
            ruta_completa = os.path.join(REPO_BASE_PATH, ruta_relativa)
            if os.path.exists(ruta_completa):
                try:
                    with open(ruta_completa, 'r', encoding='utf-8', errors='ignore') as f_src:
                        lineas = f_src.readlines()
                        inicio = max(0, func.get('linea_inicio', 1) - 1)
                        fin = func.get('linea_fin', len(lineas))
                        codigo_original = "".join(lineas[inicio:fin])
                except Exception as e:
                    codigo_original = f"Error leyendo: {e}"
                    
        func['codigo_original'] = codigo_original

        print(f"\n--- Análisis de: {func['_meta_analisis']['esquema_padre']}::{nombre} ---")
        if isinstance(res_ia, Exception):
             print(f"ERROR LLM: {res_ia}")
             func['analisis_ia'] = {'error': str(res_ia)}
        else:
             print(f"Resumen: {res_ia.get('resumen_funcional')}")
             print(f"Modifica Estado: {res_ia.get('modifica_estado')}")
             print("Reglas: " + ", ".join(res_ia.get('reglas_de_negocio', [])))
             func['analisis_ia'] = res_ia
             
        resultados_finales.append(func)

    # Guardar en archivo para inspección del usuario
    output_path = 'data/resultado_agente_ia.json'
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(resultados_finales, f, indent=2, ensure_ascii=False)
        
    print(f"\n--- RESULTADO OBTENIDO: El análisis completo se ha guardado en '{output_path}'")

if __name__ == '__main__':
    # Necesario para evitar problemas en Windows con asyncio
    if os.name == 'nt':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    
    asyncio.run(run_analysis('data/outputJAVA_clean.json'))
