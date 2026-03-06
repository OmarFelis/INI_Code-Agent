import json
import os
import httpx
import asyncio
import sys

# Forzar salida en utf-8 para evitar errores en Windows
sys.stdout.reconfigure(encoding='utf-8')

API_URL = "http://127.0.0.1:8001/api/v1/analyze"

async def main():
    print("Leyendo resultados del escaneo...")
    with open("data/JSONMASIVO.txt", "r", encoding="utf-8") as f:
        scan_data = json.load(f)
    
    project_path = scan_data.get("project_path")
    if not project_path:
        print("Error: No se encontro 'project_path' en el JSON.")
        return

    archivos_fuente = scan_data.get("results", {}).get("archivos_fuente", [])
    # Crear un diccionario para mapear nombre de archivo simple a ruta relativa completa
    mapa_archivos = {a.get("nombre"): a.get("ruta_archivo") for a in archivos_fuente}

    unidades = scan_data.get("results", {}).get("unidades_logicas", [])
    funciones = [u for u in unidades if u.get("tipo") == "FUNCION"]
    
    if not funciones:
        print("Error: No se encontraron funciones en el resultado del escaneo.")
        return
        
    print(f"Encontradas {len(funciones)} funciones. Seleccionando las 2 mas complejas para la prueba IA...")
    
    funciones_top = sorted(funciones, key=lambda x: x.get("complejidad", 0), reverse=True)[:2]
    
    payload_funciones = []
    
    for func in funciones_top:
        nombre_archivo_simple = func.get("archivo")
        ruta_relativa = mapa_archivos.get(nombre_archivo_simple)
        
        if not ruta_relativa:
            print(f"Advertencia: No se encontro la ruta relativa para {nombre_archivo_simple}")
            continue
            
        archivo_absoluto = os.path.join(project_path, ruta_relativa)
        
        try:
            with open(archivo_absoluto, "r", encoding="utf-8") as file_source:
                lines = file_source.readlines()
                inicio = func.get("linea_inicio", 1) - 1
                fin = func.get("linea_fin", len(lines))
                
                codigo_original = "".join(lines[inicio:fin])
                
                payload_funciones.append({
                    "nombre_funcion": func.get("nombre"),
                    "componente": func.get("parent") or "Standalone",
                    "archivo": ruta_relativa,
                    "lineas": f"{inicio+1}-{fin}",
                    "codigo_original": codigo_original
                })
        except Exception as e:
            print(f"No se pudo leer el archivo {archivo_absoluto}: {e}")
            continue

    if not payload_funciones:
        print("[ERROR] No se pudo extraer el codigo de ninguna funcion.")
        return

    payload = {
        "project_path": project_path,
        "funciones": payload_funciones
    }
    
    print(f"Preparando envio de {len(payload_funciones)} funciones al API de IA ({API_URL})...")
    
    async with httpx.AsyncClient(timeout=120.0) as client:
        try:
            response = await client.post(API_URL, json=payload)
            response.raise_for_status()
            resultado_ia = response.json()
            
            print("\n[EXITO] RESPUESTA DE LA IA RECIBIDA\n")
            
            with open("data/RESULTADO_IA_PRUEBA.txt", "w", encoding="utf-8") as out:
                json.dump(resultado_ia, out, indent=2, ensure_ascii=False)
            print("Resultado guardado en 'data/RESULTADO_IA_PRUEBA.txt'")
            
        except httpx.HTTPError as exc:
            print(f"\n[ERROR] Error al comunicarse con la API: {exc}")
            if hasattr(exc, "response") and exc.response:
                print(exc.response.text)

if __name__ == "__main__":
    asyncio.run(main())
