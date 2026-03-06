import os
import stat
import shutil
import asyncio
import structlog
import subprocess
from urllib.parse import urlparse

from src.config import settings

logger = structlog.get_logger()

def _remove_readonly(func, path, excinfo):
    """
    Error handler for shutil.rmtree to overcome read-only files (e.g. .git objects) on Windows.
    """
    os.chmod(path, stat.S_IWRITE)
    func(path)

async def clone_repository(repo_url: str, dest_dir: str) -> str:
    """
    Asynchronously clones a Git repository to dest_dir.
    If GIT_USERNAME and GIT_TOKEN are set, injects them into the URL for basic auth.
    """
    log = logger.bind(repo_url=repo_url, dest_dir=dest_dir)
    log.info("clone_repository_started")

    # Inyectar username en la URL si existe
    final_url = repo_url
    if settings.git_username:
        try:
            parsed = urlparse(repo_url)
            if not parsed.username:
                final_url = f"{parsed.scheme}://{settings.git_username}@{parsed.netloc}{parsed.path}"
        except Exception as e:
            log.warning("error_injecting_git_credentials", error=str(e))
            final_url = repo_url

    # Resolver ejecutable de git (importante en Windows para asyncio)
    git_exec = shutil.which("git")
    if not git_exec:
        raise RuntimeError("Git executable not found in system PATH.")

    # Construir el comando: username en la URL + Git Credential Manager del SO se encarga del password
    cmd = [git_exec, "clone", "--depth", "1", final_url, dest_dir]

    log.info("git_clone_executing", command_safe=f"git clone --depth 1 {parsed.scheme}://{settings.git_username or ''}@***/{parsed.path} {dest_dir}")

    # Ejecutar el subproceso usando to_thread para evitar NotImplementedError en Windows
    def _run_git():
        return subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False
        )

    process_result = await asyncio.to_thread(_run_git)

    if process_result.returncode != 0:
        error_msg = process_result.stderr.strip()
        
        # Enmascarar token en el log si existe en el error
        if settings.git_token and settings.git_token in error_msg:
            error_msg = error_msg.replace(settings.git_token, "***TOKEN***")
            
        log.error("git_clone_failed", return_code=process_result.returncode, error=error_msg)
        raise RuntimeError(f"Git clone failed: {error_msg}")

    log.info("clone_repository_success")
    return dest_dir

def cleanup_repository(repo_path: str):
    """
    Synchronously deletes the cloned repository from the local filesystem.
    Forces deletion of read-only files created by git.
    """
    if os.path.exists(repo_path):
        try:
            shutil.rmtree(repo_path, onerror=_remove_readonly)
            logger.info("cleanup_repository_success", repo_path=repo_path)
        except Exception as e:
            logger.error("cleanup_repository_failed", repo_path=repo_path, error=str(e))
    else:
        logger.warning("cleanup_repository_not_found", repo_path=repo_path)
