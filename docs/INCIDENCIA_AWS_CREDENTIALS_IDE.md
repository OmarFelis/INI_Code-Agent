# Incidencia: Credenciales AWS no resueltas desde el IDE (Amazon Q)

**Fecha:** 2026-03-03  
**Proyecto:** doc-as-codePRO v3.0  
**Entorno:** Windows 10, AWS CLI v2.33.26, Amazon Q IDE plugin

---

## Síntoma

Al ejecutar código Python con `boto3` desde la terminal integrada del IDE (Amazon Q), se obtiene:

```
botocore.exceptions.NoCredentialsError: Unable to locate credentials
```

o bien:

```
botocore.exceptions.ProfileNotFound: The config profile (AmazonBedrockLimitedAccess-460896925620) could not be found
```

Esto ocurre aunque el perfil SSO esté correctamente configurado en `~/.aws/config` y el login SSO haya sido exitoso.

---

## Causa raíz

El plugin de Amazon Q IDE inyecta su propia variable de entorno `AWS_CONFIG_FILE` apuntando a un archivo temporal vacío:

```
AWS_CONFIG_FILE=C:\Users\OCARDE~1\AppData\Local\Temp\empty5141694125421452420.tmp
```

Esto sobreescribe la variable del sistema, haciendo que `boto3` y `botocore` lean un config vacío en lugar de `~/.aws/config`. Como resultado, ningún perfil SSO es encontrado.

Adicionalmente, `load_dotenv()` por defecto **no sobreescribe** variables de entorno que ya existen en el proceso — por lo que aunque el `.env` tenga `AWS_CONFIG_FILE` correcto, el valor del IDE prevalece.

---

## Diagnóstico paso a paso

```cmd
echo %AWS_CONFIG_FILE%
# Resultado: C:\Users\OCARDE~1\AppData\Local\Temp\empty5141694125421452420.tmp

type "C:\Users\OCARDE~1\AppData\Local\Temp\empty5141694125421452420.tmp"
# Resultado: (vacío)
```

Esto confirma que el IDE reemplaza el config file con uno vacío.

---

## Solución

### 1. Configurar `.env` con las rutas correctas

```env
AWS_CONFIG_FILE=C:/Users/<tu-usuario>/.aws/config
AWS_PROFILE=AmazonBedrockLimitedAccess-460896925620
```

### 2. Usar `load_dotenv(override=True)` en el código

El parámetro `override=True` fuerza que los valores del `.env` sobreescriban las variables de entorno existentes del proceso (incluyendo las inyectadas por el IDE):

```python
from dotenv import load_dotenv
load_dotenv(override=True)  # <-- crítico: sin esto, el IDE gana
import boto3, os

profile = os.getenv("AWS_PROFILE")
session = boto3.Session(profile_name=profile) if profile else boto3.Session()
client = session.client("bedrock", region_name="us-east-1")
```

### 3. Autenticar la sesión SSO (si no está activa)

Desde una terminal externa al IDE (PowerShell o CMD del sistema):

```powershell
aws sso login --sso-session codeagent
```

La sesión dura ~8 horas. Cuando expire, repetir este comando.

---

## Comportamiento en producción (AWS)

En producción el problema no existe. Cuando el servicio corre en EC2, ECS o Lambda con un **IAM Role** adjunto que tenga permisos `AmazonBedrockLimitedAccess`, `boto3` resuelve las credenciales automáticamente via el metadata service de la instancia — sin `.env`, sin perfiles, sin `AWS_CONFIG_FILE`.

```python
# En produccion esto funciona sin ninguna configuracion adicional:
client = boto3.client("bedrock", region_name="us-east-1")
```

El `.env` con `AWS_CONFIG_FILE` y `AWS_PROFILE` es exclusivo del entorno de desarrollo local.

---

## Resumen de la solución

| Problema | Causa | Fix |
|---|---|---|
| `NoCredentialsError` en IDE | `AWS_CONFIG_FILE` apunta a archivo vacío del IDE | Agregar `AWS_CONFIG_FILE` real al `.env` |
| `.env` ignorado | `load_dotenv()` no sobreescribe vars existentes | Usar `load_dotenv(override=True)` |
| Perfil SSO no encontrado | Sesión SSO no autenticada | `aws sso login --sso-session codeagent` desde terminal externa |

---

## Archivos relevantes

- `.env` — contiene `AWS_CONFIG_FILE` y `AWS_PROFILE`
- `~/.aws/config` — contiene el perfil `AmazonBedrockLimitedAccess-460896925620` con `sso-session = codeagent`
- Todo código que use `boto3` debe llamar `load_dotenv(override=True)` antes de importar boto3
