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
    Asynchronously clones a Git repository to dest_dir using SSH.
    Converts HTTPS Bitbucket URLs to SSH format automatically.
    """
    log = logger.bind(repo_url=repo_url, dest_dir=dest_dir)
    log.info("clone_repository_started")

    # Convertir HTTPS a SSH para Bitbucket
    final_url = repo_url
    if "bitbucket.org" in repo_url and repo_url.startswith("https://"):
        parsed = urlparse(repo_url)
        workspace_repo = parsed.path.lstrip("/")
        final_url = f"git@bitbucket.org:{workspace_repo}"
        if not final_url.endswith(".git"):
            final_url += ".git"

    # Resolver ejecutable de git
    git_exec = shutil.which("git")
    if not git_exec:
        raise RuntimeError("Git executable not found in system PATH.")

    cmd = [git_exec, "clone", "--depth", "1", final_url, dest_dir]
    log.info("git_clone_executing", command_safe=f"git clone --depth 1 {final_url} {dest_dir}")

    def _run_git():
        return subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
            env={**os.environ, "GIT_SSH_COMMAND": "ssh -i /tmp/id_ed25519 -o StrictHostKeyChecking=no"}
        )

    process_result = await asyncio.to_thread(_run_git)

    if process_result.returncode != 0:
        error_msg = process_result.stderr.strip()
        log.error("git_clone_failed", return_code=process_result.returncode, error=error_msg)
        raise RuntimeError(f"Git clone failed: {error_msg}")

    log.info("clone_repository_success")
    return dest_dir

def get_commit_hash(repo_path: str) -> str | None:
    """
    Returns the HEAD commit hash of a cloned repository, or None if it fails.
    """
    try:
        git_exec = shutil.which("git") or "git"
        result = subprocess.run(
            [git_exec, "rev-parse", "HEAD"],
            capture_output=True, text=True, check=False, cwd=repo_path
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception as e:
        logger.warning("get_commit_hash_failed", repo_path=repo_path, error=str(e))
    return None


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
