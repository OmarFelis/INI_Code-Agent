# Plan de Implementación — Soporte GitHub SSH

> Proyecto: Code-Agent
> Fecha: Junio 2026
> Objetivo: Extender el clonado de repositorios para soportar GitHub además de Bitbucket, usando SSH keys por proveedor

---

## 1. Contexto y Estado Actual

### Cómo funciona hoy el clonado (Bitbucket)

```
docker-compose.override.yml
    │
    ├── Monta: C:/Users/ocardenas/.ssh/codeagent_bitbucket → /root/.ssh/id_ed25519
    └── Al arrancar: cp /root/.ssh/id_ed25519 /tmp/id_ed25519 && chmod 600

scm_adapter.py → clone_repository()
    │
    ├── Si URL es HTTPS de bitbucket.org → convierte a git@bitbucket.org:org/repo.git
    └── Siempre usa: GIT_SSH_COMMAND="ssh -i /tmp/id_ed25519 -o StrictHostKeyChecking=no"
```

### Problema actual

- La ruta `/tmp/id_ed25519` está **hardcodeada** en `scm_adapter.py`
- No hay lógica para seleccionar una clave distinta según el proveedor
- `GIT_USERNAME` y `GIT_TOKEN` están en `.env` pero **no se usan** en el flujo de clonado
- No hay conversión HTTPS → SSH para URLs de GitHub
- `GIT_SSH_COMMAND` está definida **en dos lugares**: como variable de entorno en `docker-compose.override.yml` y hardcodeada en `scm_adapter.py` (el código Python sobreescribe la variable del entorno, haciéndola redundante)
- No existe `.env.example` ni plantilla de `docker-compose.override.yml` para onboarding de nuevos desarrolladores

---

## 2. Decisión de Diseño — SSH Key por Proveedor

Se mantiene el enfoque SSH (no HTTPS+Token) por las siguientes razones:

| Criterio | SSH Key | HTTPS + Token |
|---|---|---|
| Arquitectura actual | ✅ Ya implementada y funcionando | Requiere refactor completo |
| Seguridad | ✅ Clave privada nunca viaja en la URL | Token visible en logs si no se maneja bien |
| Docker | ✅ Volumen montado, patrón ya establecido | Requiere inyección de token en runtime |
| Consistencia | ✅ Mismo patrón para ambos proveedores | Mezclaría dos mecanismos distintos |

> `GIT_USERNAME` y `GIT_TOKEN` en `.env` quedan como variables documentadas pero no se usan en el flujo SSH. Se pueden remover en una limpieza futura o conservar para un posible fallback HTTPS.

---

## 3. Archivos a Modificar

| Archivo | Qué cambia |
|---|---|
| `docker-compose.override.yml` | Montar SSH key de GitHub como segundo volumen, copiarla al arrancar, **eliminar `GIT_SSH_COMMAND` redundante** |
| `src/config.py` | Agregar `bitbucket_ssh_key_path` y `github_ssh_key_path` como variables configurables |
| `src/core/scm/scm_adapter.py` | Detectar proveedor por dominio, convertir HTTPS→SSH para GitHub, seleccionar clave correcta, **validar existencia de SSH key** |
| `.env.example` | **[NUEVO]** Documentar todas las variables del proyecto incluyendo las nuevas |
| `docker-compose.override.example.yml` | **[NUEVO]** Plantilla versionada del override para onboarding |

---

## 4. Detalle de Cambios por Archivo

### 4.1 `docker-compose.override.yml`

Agregar un segundo volumen para la SSH key de GitHub, copiarla en el comando de arranque, y **eliminar la variable `GIT_SSH_COMMAND`** (es redundante porque `scm_adapter.py` la sobreescribe en código).

```
ANTES:
  volumes:
    - C:/Users/ocardenas/.ssh/codeagent_bitbucket:/root/.ssh/id_ed25519:ro
    - C:/:/host:ro
  environment:
    GIT_SSH_COMMAND: "ssh -i /tmp/id_ed25519 -o StrictHostKeyChecking=no"   ← REDUNDANTE, se elimina
  command: sh -c "cp /root/.ssh/id_ed25519 /tmp/id_ed25519 && chmod 600 /tmp/id_ed25519 && uvicorn ..."

DESPUÉS:
  volumes:
    - C:/Users/ocardenas/.ssh/codeagent_bitbucket:/root/.ssh/id_ed25519:ro
    - C:/Users/ocardenas/.ssh/codeagent_github:/root/.ssh/id_ed25519_github:ro   ← NUEVO
    - C:/:/host:ro
  # GIT_SSH_COMMAND ELIMINADO — la selección de clave SSH se hace en scm_adapter.py
  command: sh -c "
    cp /root/.ssh/id_ed25519 /tmp/id_ed25519 && chmod 600 /tmp/id_ed25519 &&
    cp /root/.ssh/id_ed25519_github /tmp/id_ed25519_github && chmod 600 /tmp/id_ed25519_github &&   ← NUEVO
    uvicorn ..."
```

> ⚠️ La SSH key de GitHub aún no existe. Completar la sección 6 antes de aplicar este cambio en el override.

---

### 4.2 `src/config.py`

Agregar dos variables en la sección `# --- Security SCM ---`:

```
ANTES:
  git_username: str | None
  git_token: str | None

DESPUÉS (se agregan):
  bitbucket_ssh_key_path: str  → default "/tmp/id_ed25519"
  github_ssh_key_path: str     → default "/tmp/id_ed25519_github"
```

Los defaults coinciden con las rutas que el override copia al arrancar, por lo que en local funciona sin configuración adicional.

---

### 4.3 `src/core/scm/scm_adapter.py`

Cuatro cambios en la función `clone_repository()`:

**Cambio 1 — Conversión HTTPS → SSH para GitHub** (igual que ya existe para Bitbucket):
```
Si URL contiene "github.com" y empieza con "https://"
    → convertir a git@github.com:org/repo.git
```

**Cambio 2 — Selección de SSH key según proveedor**:
```
Si "bitbucket.org" en final_url → usar settings.bitbucket_ssh_key_path
Si "github.com" en final_url    → usar settings.github_ssh_key_path
Si ninguno coincide             → RuntimeError("No SSH key configured for domain: {domain}")
```

**Cambio 3 — Eliminar la ruta hardcodeada**:
```
ANTES:
  "GIT_SSH_COMMAND": "ssh -i /tmp/id_ed25519 -o StrictHostKeyChecking=no"

DESPUÉS:
  ssh_key = <seleccionada según proveedor>
  "GIT_SSH_COMMAND": f"ssh -i {ssh_key} -o StrictHostKeyChecking=no"
```

**Cambio 4 — Validación de existencia de SSH key** (nuevo):
```python
# Antes de ejecutar git clone, verificar que la clave existe
if not os.path.exists(ssh_key):
    raise RuntimeError(f"SSH key not found at {ssh_key}. Check Docker volume mounts.")
```
> Esto evita errores crípticos de SSH cuando la clave no está montada correctamente.

---

### 4.4 `.env.example` [NUEVO]

Crear archivo `.env.example` (actualmente no existe en el proyecto) documentando todas las variables, incluyendo las nuevas:

```
# --- SSH Keys para clonado de repositorios ---
BITBUCKET_SSH_KEY_PATH=/tmp/id_ed25519
GITHUB_SSH_KEY_PATH=/tmp/id_ed25519_github
```

---

### 4.5 `docker-compose.override.example.yml` [NUEVO]

Crear una plantilla versionada (commiteable) que sirva de referencia para nuevos desarrolladores:

```yaml
# ============================================
# docker-compose.override.yml — PLANTILLA
# Copiar como docker-compose.override.yml y ajustar rutas
# ============================================
services:
  api:
    volumes:
      - ~/.ssh/codeagent_bitbucket:/root/.ssh/id_ed25519:ro
      - ~/.ssh/codeagent_github:/root/.ssh/id_ed25519_github:ro
    command: >
      sh -c "cp /root/.ssh/id_ed25519 /tmp/id_ed25519 && chmod 600 /tmp/id_ed25519 &&
             cp /root/.ssh/id_ed25519_github /tmp/id_ed25519_github && chmod 600 /tmp/id_ed25519_github &&
             uvicorn src.api.main:app --host 0.0.0.0 --port 8000 --reload"
```

> Este archivo **sí se versiona** en Git, a diferencia de `docker-compose.override.yml` que está en `.gitignore`.

---

## 5. Flujo Final (después del cambio)

```
POST /scan { repo_url: "https://github.com/org/repo" }
    │
    ▼
clone_repository(repo_url)
    │
    ├── Detecta: "github.com" en URL
    ├── Convierte: https://github.com/org/repo → git@github.com:org/repo.git
    ├── Selecciona: settings.github_ssh_key_path → /tmp/id_ed25519_github
    └── Ejecuta: git clone --depth 1 git@github.com:org/repo.git <dest>
                 con GIT_SSH_COMMAND="ssh -i /tmp/id_ed25519_github -o StrictHostKeyChecking=no"

POST /scan { repo_url: "https://bitbucket.org/org/repo" }
    │
    ├── Detecta: "bitbucket.org" en URL
    ├── Convierte: https://bitbucket.org/org/repo → git@bitbucket.org:org/repo.git
    ├── Selecciona: settings.bitbucket_ssh_key_path → /tmp/id_ed25519
    └── Ejecuta: git clone --depth 1 git@bitbucket.org:org/repo.git <dest>
                 con GIT_SSH_COMMAND="ssh -i /tmp/id_ed25519 -o StrictHostKeyChecking=no"
```

---

## 6. Pre-requisito — Generar SSH Key para GitHub

Si aún no tienes el archivo `codeagent_github` en tu máquina, hay que generarlo:

```bash
# Generar la clave (en tu máquina local, no en el contenedor)
ssh-keygen -t ed25519 -C "codeagent-github" -f C:/Users/ocardenas/.ssh/codeagent_github

# Esto genera dos archivos:
#   codeagent_github      ← clave privada (va al volumen Docker)
#   codeagent_github.pub  ← clave pública (se registra en GitHub)
```

Luego registrar `codeagent_github.pub` en GitHub:
- `GitHub → Settings → SSH and GPG keys → New SSH key`
- Tipo: **Authentication Key**
- Pegar el contenido de `codeagent_github.pub`

---

## 7. Checklist de Validación

- [x] SSH key de GitHub generada en `C:/Users/ocardenas/.ssh/codeagent_github`
- [x] Clave pública registrada en GitHub Settings
- [ ] `docker-compose.override.yml` monta ambos volúmenes y **no tiene `GIT_SSH_COMMAND`**
- [ ] Contenedor arranca sin errores y ambas claves existen en `/tmp/`
- [ ] `config.py` expone `bitbucket_ssh_key_path` y `github_ssh_key_path`
- [ ] `scm_adapter.py` selecciona la clave correcta según el dominio
- [ ] `scm_adapter.py` valida existencia de SSH key antes de clonar
- [ ] Clonar un repo de Bitbucket sigue funcionando (no regresión)
- [ ] Clonar un repo de GitHub funciona con la nueva clave
- [ ] `.env.example` creado y versionado
- [ ] `docker-compose.override.example.yml` creado y versionado

---

## 8. Impacto y Riesgos

| Riesgo | Mitigación |
|---|---|
| Regresión en Bitbucket | El default de `bitbucket_ssh_key_path` es `/tmp/id_ed25519`, idéntico al hardcodeado actual |
| SSH key de GitHub no registrada en GitHub | Checklist de pre-requisitos (sección 6) |
| Ruta del archivo incorrecta en override | Validación en código: `RuntimeError` si la clave no existe en el path configurado |
| URL de GitHub en formato SSH directo (ya viene como `git@github.com:...`) | La conversión HTTPS→SSH solo aplica si la URL empieza con `https://`, no rompe URLs SSH directas |
| `GIT_SSH_COMMAND` redundante causa confusión | Eliminada del override; selección de clave se centraliza en `scm_adapter.py` |

---

*Documento de propuesta — Code-Agent — Soporte GitHub SSH*
*Para revisión y validación antes de implementar*
