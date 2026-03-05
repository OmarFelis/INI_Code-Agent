import urllib.request
import json

def fetch_scan():
    url = 'http://localhost:8001/api/v1/scan'
    # Usando UUIDs permitidos por Pydantic (UUID4 genérico suele funcionar si no se fuerza UUID7)
    payload = {
        "project_path": "/host/FLOTAS - Assessments/flotas-mod_empresa",
        "branch": "main",
        "microservice_name": "FLOTAS-MOD-EMPRESA",
        "aplicacion_id": "12345678-1234-5678-1234-567812345678",
        "activo_id": "12345678-1234-5678-1234-567812345678"
    }
    
    data = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json'})
    
    try:
        print("Enviando request a FastAPI...")
        res = urllib.request.urlopen(req)
        response_data = res.read().decode('utf-8')
        
        with open('data/outputJAVA_clean.json', 'w', encoding='utf-8') as f:
            f.write(response_data)
        print("Escaneo grabado exitosamente en data/outputJAVA_clean.json")
    except urllib.error.HTTPError as e:
        error_body = e.read().decode('utf-8')
        print(f"Error HTTP {e.code}: {error_body}")
    except Exception as e:
        print(f"Error inesperado: {e}")

if __name__ == '__main__':
    fetch_scan()
