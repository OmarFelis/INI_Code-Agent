"""
Patch project_path del job a una ruta local para poder re-enriquecer.
El cache LLM absorberá la mayoría de llamadas sin gastar tokens.

Uso:
  python patch_job_path.py <nueva_ruta_local_del_repo>

Ejemplo:
  python patch_job_path.py C:/INI_Code-Agent/repos_cache/8cd84d40-2de4-461a-87ef-a8b52846e278
"""
import asyncio
import sys
from uuid import UUID
from sqlalchemy import update
sys.path.insert(0, '.')
from src.db.session import async_session_factory
from src.db.models import EscaneoORM
from src.db import repository

JOB_ID = UUID('8cd84d40-2de4-461a-87ef-a8b52846e278')

async def main():
    if len(sys.argv) < 2:
        print("Uso: python patch_job_path.py <ruta_local_repo>")
        print("\nEjemplo:")
        print("  python patch_job_path.py C:/ruta/al/repo/transactionkey_private_fn_put_visa-v10-regulator")
        return

    nueva_ruta = sys.argv[1]
    import os
    if not os.path.isdir(nueva_ruta):
        print(f"ERROR: La ruta no existe o no es un directorio: {nueva_ruta}")
        return

    async with async_session_factory() as s:
        job = await repository.get_scan_job(s, JOB_ID)
        print(f"project_path actual: {job.project_path}")
        print(f"Actualizando a:      {nueva_ruta}")

        await s.execute(
            update(EscaneoORM)
            .where(EscaneoORM.id == JOB_ID)
            .values(project_path=nueva_ruta)
        )
        await s.commit()
        print("✅ project_path actualizado en DB")
        print(f"\nAhora llama al endpoint:")
        print(f"  POST /api/v1/scan/{JOB_ID}/enrich-all")
        print(f"\nEl cache LLM tiene 6138 entradas — la mayoría serán cache hits sin gastar tokens.")

asyncio.run(main())
