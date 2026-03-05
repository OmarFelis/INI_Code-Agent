import json
import asyncio
import os
import aiohttp

# --- CONFIGURACIÓN MOCK PARA LLM ---
# En producción esto usará boto3 para AWS Bedrock o el cliente de OpenAI.
# Simularemos un endpoint local o un mock delay.

OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL_NAME = "llama3.1" # o el modelo que tengas local, o mock

async def mock_llm_call(session, prompt: str, function_name: str) -> dict:
    """
    Simula o ejecuta una llamada real a un LLM asíncronamente.
    """
    try:
        # Intento conectarme a un Ollama local si existe (para pruebas reales)
        payload = {
            "model": MODEL_NAME,
            "prompt": prompt,
            "stream": False,
            "format": "json"
        }
        async with session.post(OLLAMA_URL, json=payload, timeout=5) as response:
            if response.status == 200:
                data = await response.json()
                return json.loads(data['response'])
    except Exception:
        # Fallback a un mock si Ollama no está corriendo
        pass

    await asyncio.sleep(0.5) # Simula latencia
    return {
        "resumen_funcional": f"Función {function_name} procesada correctamente.",
        "modifica_estado": "update" in function_name.lower() or "save" in function_name.lower(),
        "reglas_de_negocio": [
            f"Validación 1 para {function_name}",
            f"Condición de error encontrada en {function_name}"
        ]
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
async def analizar_lote_concurrente(funciones_batch: list, session) -> list:
    tareas = []
    for func in funciones_batch:
        prompt = PROMPT_TACTICO.format(
            nombre_funcion=func['nombre'],
            esquema_clase=func['_meta_analisis']['esquema_padre']
        )
        # LLamada asíncrona concurrente
        tareas.append(mock_llm_call(session, prompt, func['nombre']))
        
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
    
    async with aiohttp.ClientSession() as session:
        # 4. Análisis Concurrente (Estrategia 4)
        resultados_ia = await analizar_lote_concurrente(batch_prueba, session)
        
    # Mostrar resultados
    print("\n--- Resultados de la IA ---")
    for idx, func in enumerate(batch_prueba):
        nombre = func['nombre']
        res_ia = resultados_ia[idx]
        print(f"\n--- Análisis de: {func['_meta_analisis']['esquema_padre']}::{nombre} ---")
        if isinstance(res_ia, Exception):
             print(f"ERROR LLM: {res_ia}")
        else:
             print(f"Resumen: {res_ia.get('resumen_funcional')}")
             print(f"Modifica Estado: {res_ia.get('modifica_estado')}")
             print("Reglas: " + ", ".join(res_ia.get('reglas_de_negocio', [])))

if __name__ == '__main__':
    # Necesario para evitar problemas en Windows con asyncio
    if os.name == 'nt':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    
    asyncio.run(run_analysis('data/outputJAVA_clean.json'))
