import argparse
import urllib.request
import json
import os
import sys
import ai_prototype
import asyncio

API_URL = 'http://localhost:8001/api/v1/scan'

def fase1_escaneo_ast(ruta_local: str, output_file: str) -> bool:
    print(f"\n[FASE 1] Solicitando escaneo AST local para: {ruta_local}")
    
    # Payload base (hardcodeado temporalmente pero parametrizable)
    payload = {
        "project_path": ruta_local,
        "branch": "main",
        "microservice_name": ruta_local.split("/")[-1] if "/" in ruta_local else "Proyecto-Local",
        "aplicacion_id": "12345678-1234-5678-1234-567812345678",
        "activo_id": "12345678-1234-5678-1234-567812345678"
    }
    
    data = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(API_URL, data=data, headers={'Content-Type': 'application/json'})
    
    try:
        res = urllib.request.urlopen(req)
        response_data = res.read().decode('utf-8')
        
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(response_data)
        print(f"--- FASE 1 COMPLETADA: Resultado JSON guardado en {output_file}")
        return True
    except urllib.error.HTTPError as e:
        error_body = e.read().decode('utf-8')
        print(f"ERROR Fase 1 (HTTP {e.code}): {error_body}")
        return False
    except Exception as e:
        print(f"ERROR inesperado Fase 1: {e}")
        return False

def fase2_agentic_llm(json_file: str):
    print(f"\n[FASE 2] Iniciando Análisis Agentic (LLM) sobre: {json_file}")
    
    # Solución de compatibilidad Asyncio en Windows
    if os.name == 'nt':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        
    try:
        # Llamamos directo a la función de tu prototipo!
        asyncio.run(ai_prototype.run_analysis(json_file))
        print(f"--- FASE 2 COMPLETADA")
    except Exception as e:
        print(f"ERROR en Fase 2: {e}")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Ejecutar Fase 1 (AST) y Fase 2 (LLM Agentic) juntas.')
    parser.add_argument('--path', type=str, required=True, help='Ruta absoluta del repo a evaluar (usar formato /host/... si corre en Docker C:/)')
    parser.add_argument('--out', type=str, default='data/resultado_pipeline.json', help='Archivo temporal JSON de salida')
    
    args = parser.parse_args()
    
    print("=====================================================")
    print(" --- PIPELINE CODE-AGENT E2E (REAL AWS BEDROCK) ---")
    print("=====================================================")
    
    exito_fase1 = fase1_escaneo_ast(args.path, args.out)
    
    if exito_fase1:
        fase2_agentic_llm(args.out)
    else:
        print("\nAbortando Fase 2 debido a falla en Fase 1.")
