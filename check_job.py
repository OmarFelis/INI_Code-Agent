import asyncio
import sys
sys.path.insert(0, '.')
from uuid import UUID
from src.db.session import async_session_factory
from src.db import repository

JOB_ID = UUID('8cd84d40-2de4-461a-87ef-a8b52846e278')

async def main():
    async with async_session_factory() as s:
        job = await repository.get_scan_job(s, JOB_ID)
        print(f"project_path: {job.project_path}")
        print(f"status: {job.status}")
        print(f"microservice: {job.microservice_name}")

        archivos = await repository.get_archivos_by_escaneo(s, JOB_ID)
        unidades = await repository.get_unidades_by_escaneo(s, JOB_ID)

        archivos_sin_ia = [a for a in archivos if not a.analisis_ia]
        unidades_sin_ia = [u for u in unidades if not u.analisis_ia]

        print(f"\nArchivos totales: {len(archivos)}")
        print(f"Archivos SIN analisis_ia: {len(archivos_sin_ia)}")
        print(f"Unidades totales: {len(unidades)}")
        print(f"Unidades SIN analisis_ia: {len(unidades_sin_ia)}")

        if archivos:
            print(f"\nEjemplo ruta_archivo: {archivos[0].ruta_archivo}")

asyncio.run(main())
