# Aprendizajes: Autenticación Git con Bitbucket Cloud (2026)

## Contexto
Durante la implementación del clonado remoto de repositorios en el Code-Agent, se probaron múltiples métodos de autenticación para `git clone` contra repositorios privados de Bitbucket Cloud. Este documento resume lo que funciona, lo que NO funciona, y por qué.

---

## ❌ Métodos que NO funcionan para `git clone`

### 1. API Tokens de Bitbucket como Basic Auth en URL
```bash
# NO FUNCIONA
git clone https://usuario:API_TOKEN@bitbucket.org/workspace/repo.git
```
Los nuevos **API Tokens** (reemplazo de App Passwords desde Sept 2025) **no son compatibles** con autenticación HTTP Basic Auth embebida en la URL para operaciones de Git.

### 2. API Tokens como Bearer Header
```bash
# NO FUNCIONA
git -c "http.extraHeader=Authorization: Bearer API_TOKEN" clone https://bitbucket.org/workspace/repo.git
```
Tampoco funcionan como tokens Bearer en headers HTTP para operaciones Git.

### 3. Usuario especial `x-token-auth`
```bash
# NO FUNCIONA
git clone https://x-token-auth:API_TOKEN@bitbucket.org/workspace/repo.git
```
Este patrón era válido para App Passwords antiguas, no para los nuevos API Tokens.

### 4. App Passwords (Deprecadas)
Desde el **9 de septiembre de 2025**, Bitbucket dejó de permitir la creación de App Passwords. Las existentes se deshabilitarán el **9 de junio de 2026**.

---

## ✅ Método que SÍ funciona: Git Credential Manager (GCM)

### Cómo funciona
```bash
# FUNCIONA ✅
git clone https://usuario@bitbucket.org/workspace/repo.git
```

- Se inyecta **solo el username** en la URL (sin password ni token).
- El **Git Credential Manager** (GCM) de Windows/macOS se encarga automáticamente de la autenticación usando credenciales cacheadas del sistema operativo.
- GCM almacena las credenciales en el **Windows Credential Store** (o Keychain en macOS).

### Pre-requisitos
1. Git para Windows debe estar instalado con GCM habilitado (viene habilitado por defecto).
2. El usuario debe haber clonado o autenticado al menos una vez contra Bitbucket desde su máquina (para que GCM cachee las credenciales).
3. Verificar que GCM esté configurado:
```bash
git config --global credential.helper
# Debe retornar: manager o manager-core
```

### Limitaciones
- **Solo funciona en máquinas locales** donde el usuario ya se autenticó previamente.
- **No funciona en contenedores Docker** o CI/CD sin configuración adicional (no hay GCM).
- Para Docker/CI: considerar **SSH Keys** o **OAuth 2.0 Consumer Grants**.

---

## 🐛 Problemas encontrados con `subprocess` en Python (Windows)

| Problema | Causa | Solución |
|---|---|---|
| `NotImplementedError` | `asyncio.create_subprocess_exec` no soporta subprocesos en el Event Loop por defecto de Windows | Usar `subprocess.run()` envuelto en `asyncio.to_thread()` |
| `FileNotFoundError` | `asyncio` en Windows no resuelve ejecutables sin extensión `.exe` | Usar `shutil.which("git")` para obtener la ruta completa |
| `PermissionError` al borrar `.git` | Los objetos de Git son read-only en Windows | Usar `shutil.rmtree(path, onerror=handler)` con un handler que hace `os.chmod(path, stat.S_IWRITE)` |

---

## 📋 Configuración actual del Code-Agent

### Variables de entorno (`.env`)
```env
# Username para inyectar en URLs de Git
GIT_USERNAME=omarcardenas1

# Dominios permitidos para clonado (whitelist anti-SSRF)
ALLOWED_GIT_DOMAINS=bitbucket.org,github.com,gitlab.com

# Token de seguridad para consumir la API
API_SECRET_TOKEN=my-super-secret-local-token
```

### Flujo de clonación
```
POST /api/v1/scan (con repo_url)
  │
  ├── 1. Validar Bearer Token del header Authorization
  ├── 2. Validar dominio de repo_url contra ALLOWED_GIT_DOMAINS
  ├── 3. Inyectar GIT_USERNAME en la URL
  ├── 4. git clone --depth 1 → tmp_repos/{job_id}/
  ├── 5. Pipeline de análisis sobre el código clonado
  ├── 6. Guardar resultados en BD
  └── 7. FINALLY: Borrar tmp_repos/{job_id}/ (siempre)
```

---

## 🔮 Recomendaciones para Producción (Docker/CI)
1. **SSH Keys**: La opción más robusta. Montar la clave privada como secret en el contenedor.
2. **OAuth 2.0 Consumer**: Bitbucket soporta OAuth grants para operaciones automatizadas.
3. **Workspace Access Tokens**: Tokens a nivel de workspace (no de usuario) que podrían funcionar para git clone.
