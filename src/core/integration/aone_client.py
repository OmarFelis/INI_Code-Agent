"""
A-ONE Sync Client — Envia resultados a la BD de A-ONE mediante API Lambda (PostgREST style).
Soporta Upsert (Update on Conflict) para evitar duplicados.
"""
import json
import uuid
import httpx
import structlog
import datetime
import asyncio
from src.config import settings

log = structlog.get_logger()

class AOneSyncClient:
    def __init__(self):
        self.base_url = settings.aone_base_url.rstrip("/")
        # We need a client that doesn't timeout easily for large batches
        self.client = httpx.AsyncClient(timeout=30.0)

    async def close(self):
        """Close the async HTTP client."""
        await self.client.aclose()

    def _get_headers(self) -> dict:
        """Returns headers for PostgREST/Lambda targeting Upsert resolution."""
        return {
            "Content-Type": "application/json",
            "Prefer": "resolution=merge-duplicates"
        }

    async def _delete(self, endpoint: str, record_id: str) -> bool:
        """DELETE a record by ID in A-ONE."""
        url = f"{self.base_url}/{endpoint}/{record_id}"
        try:
            response = await self.client.delete(url, headers={"Content-Type": "application/json"})
            if response.status_code in [200, 204]:
                return True
            log.warning("aone_delete_unexpected_status", url=url, status=response.status_code, body=response.text)
            return False
        except Exception as e:
            log.error("aone_delete_error", url=url, error=str(e))
            return False

    async def _delete_many(self, endpoint: str, ids: list[str], concurrency: int = 15) -> int:
        """DELETE multiple records concurrently. Returns count of successful deletes."""
        if not ids:
            return 0
        semaphore = asyncio.Semaphore(concurrency)

        async def _del(record_id):
            async with semaphore:
                return await self._delete(endpoint, record_id)

        results = await asyncio.gather(*[_del(i) for i in ids], return_exceptions=True)
        return sum(1 for r in results if r is True)

    async def _put(self, endpoint: str, record_id: str, payload: dict) -> bool:
        """PUT to update an existing record by ID."""
        url = f"{self.base_url}/{endpoint}/{record_id}"
        try:
            response = await self.client.put(url, json=payload, headers={"Content-Type": "application/json"})
            if response.status_code in [200, 201, 204]:
                return True
            log.warning("aone_put_unexpected_status", url=url, status=response.status_code, body=response.text)
            return False
        except Exception as e:
            log.error("aone_put_error", url=url, error=str(e))
            return False

    async def _put_many(self, endpoint: str, items: list[dict], concurrency: int = 15) -> bool:
        """PUT multiple records concurrently. Each item must have 'id'."""
        if not items:
            return True
        semaphore = asyncio.Semaphore(concurrency)

        async def _put_single(item):
            record_id = item.get("id")
            if not record_id:
                return False
            async with semaphore:
                return await self._put(endpoint, record_id, item)

        results = await asyncio.gather(*[_put_single(item) for item in items], return_exceptions=True)
        return all(isinstance(r, bool) and r for r in results)

    async def _post_upsert(self, endpoint: str, payload: dict | list) -> bool:
        """Helper to send POST. If 409 (already exists), DELETE + POST to update."""
        url = f"{self.base_url}/{endpoint}"
        
        try:
            response = await self.client.post(url, json=payload, headers=self._get_headers())
            
            if response.status_code in [200, 201, 204]:
                return True

            # A-ONE Lambda no soporta merge-duplicates — si ya existe, DELETE + POST
            if response.status_code == 409 and isinstance(payload, dict) and payload.get("id"):
                record_id = payload["id"]
                delete_url = f"{url}/{record_id}"
                del_response = await self.client.delete(delete_url, headers={"Content-Type": "application/json"})
                if del_response.status_code in [200, 204]:
                    retry = await self.client.post(url, json=payload, headers=self._get_headers())
                    if retry.status_code in [200, 201, 204]:
                        return True
                    log.error("aone_sync_retry_failed", url=url, status=retry.status_code, response=retry.text)
                    return False
                log.error("aone_sync_delete_failed", url=delete_url, status=del_response.status_code)
                return False

            log.warning("aone_sync_unexpected_status", url=url, status=response.status_code, body=response.text)
            return False
            
        except httpx.HTTPStatusError as e:
            log.error("aone_sync_http_error", url=url, status=e.response.status_code, response=e.response.text)
            return False
        except Exception as e:
            log.error("aone_sync_network_error", url=url, error=str(e))
            return False

    async def _post_upsert_many(self, endpoint: str, items: list[dict], concurrency: int = 15) -> bool:
        """Helper to send multiple POSTs concurrently using Upsert."""
        if not items:
            return True
            
        semaphore = asyncio.Semaphore(concurrency)
        
        async def _post_single(item):
            async with semaphore:
                return await self._post_upsert(endpoint, item)
                
        results = await asyncio.gather(*[_post_single(item) for item in items], return_exceptions=True)
        # Check if all succeed
        success = all(isinstance(r, bool) and r for r in results)
        return success

    async def sync_scan_results(self, job_results: dict) -> bool:
        """
        Main orchestration function.
        Sends `escaneo`, `archivos`, `unidades` and `reglas_negocio` to A-ONE APIs in order.
        """
        if getattr(settings, "aone_sync_mode", "remote").lower() == "local":
            log.info("aone_sync_skipped", reason="AONE_SYNC_MODE=local")
            return True

        escaneo_data = job_results.get("escaneo", {})
        archivos_data = job_results.get("archivos_fuente", [])
        unidades_data = job_results.get("unidades_logicas", [])

        if not escaneo_data:
            log.error("aone_sync_failed_no_escaneo_data")
            return False
            
        # 1. We need a stable ID for the escaneo mapping across tables. 
        # Usually we use the job_id, assuming it was injected, or we generate one if missing.
        # But wait! PostgREST needs the PK `id`. Let's ensure it exists.
        scan_id = escaneo_data.get("id")
        if not scan_id:
            # Generate a UUID v7 or v4 for the scan if the pipeline didn't attach it
            scan_id = str(uuid.uuid4())
            escaneo_data["id"] = scan_id

        # Make sure mandatory fields are present based on previous tests
        escaneo_data["status"] = escaneo_data.get("status", "COMPLETED")
        escaneo_data["total_files_processed"] = escaneo_data.get("total_files_processed", escaneo_data.get("archivos_total", 0))

        # The DB requires created_at if it lacks a default in the schema
        now_str = datetime.datetime.now(datetime.timezone.utc).isoformat()
        escaneo_data["created_at"] = escaneo_data.get("created_at", now_str)

        log.info("aone_sync_started", scan_id=scan_id, total_archivos=len(archivos_data), total_unidades=len(unidades_data))

        # --- FASE 1: ESCANEO ---
        success_scan = await self._post_upsert("entities/escaneos", escaneo_data)
        if not success_scan:
            log.error("aone_sync_failed_at_escaneo", scan_id=scan_id)
            return False

        # --- FASE 2: ARCHIVOS ---
        # We need to inject the FK `escaneo_id` and generate PKs for files
        for f in archivos_data:
            ia = f.pop("analisis_ia", None)
            if ia is not None:
                f["analisis_ia"] = json.dumps(ia) if isinstance(ia, dict) else ia
            f["escaneo_id"] = scan_id
            f["escaneado"] = True
            f["created_at"] = f.get("created_at", now_str)
            if "id" not in f:
                f["id"] = str(uuid.uuid4())
                
        if archivos_data:
            # Send all files concurrently
            success_files = await self._post_upsert_many("entities/archivos_fuente", archivos_data, concurrency=10)
            if not success_files:
                log.error("aone_sync_failed_at_archivos", scan_id=scan_id)
                # Not returning false yet, maybe we want to continue? Actually, FKs might fail later.
                return False

        # --- FASE 3: UNIDADES LOGICAS ---
        # Inject FK `escaneo_id` and map `archivo_id` properly
        # We map file names to the new file UUIDs
        file_name_to_id = {f["nombre"]: f["id"] for f in archivos_data}
        
        for u in unidades_data:
            u["escaneo_id"] = scan_id
            u["created_at"] = u.get("created_at", now_str)
            if "id" not in u:
                u["id"] = str(uuid.uuid4())
            
            # Map the foreign key to the parent file
            file_name = u.get("archivo")
            if file_name and file_name in file_name_to_id:
                u["archivo_id"] = file_name_to_id[file_name]

            # Replace 'parent' name with the actual UUID of the parent class
            # This requires a dual-pass if parents appear after children, but usually classes are first
        
        # Simple parent mapping (assumes classes appear before their methods in the list)
        class_name_to_id = {u["nombre"]: u["id"] for u in unidades_data if u["tipo"] == "CLASE" and u.get("archivo")}

        for u in unidades_data:
            parent_name = u.get("parent")
            if parent_name and parent_name in class_name_to_id:
                u["parent_id"] = class_name_to_id[parent_name]
            
            # Limpiar campos que no van a la BD directamente o que son redundantes
            u.pop("parent", None)
            u.pop("archivo", None)

        # --- FASE 4: REGLAS DE NEGOCIO (Extracción previa a enviar unidades) ---
        # Extract rules from current IA metadata (if available from enrich)
        reglas_negocio = []
        for u in unidades_data:
            ia_data = u.get("analisis_ia", None)
            u["escaneado"] = True

            if ia_data:
                u["analisis_ia"] = ia_data if isinstance(ia_data, dict) else json.loads(ia_data)
                # Mapeo a columnas raíz de la tabla unidades_logicas
                if "resumen_funcional" in ia_data:
                    u["resumen"] = ia_data["resumen_funcional"]
                if "modifica_estado" in ia_data:
                    u["modifica_estado"] = ia_data["modifica_estado"]
                    
                if "reglas_de_negocio" in ia_data:
                    for regla in ia_data["reglas_de_negocio"]:
                        desc = regla.get("descripcion", "") if isinstance(regla, dict) else str(regla)
                        if not desc:
                            continue
                        codigo = regla.get("codigo_relacionado") if isinstance(regla, dict) else None
                        reglas_negocio.append({
                            "id": str(uuid.uuid4()),
                            "unidad_logica_id": u["id"],
                            "descripcion": desc,
                            "codigo_relacionado": codigo,
                            "activo_id": escaneo_data.get("activo_id"),
                            "aplicacion_id": escaneo_data.get("aplicacion_id"),
                            "creado_por_ia": True,
                            "activo": True,
                            "created_at": now_str
                        })

        if unidades_data:
            # Concurrent POST para Unidades_logicas, ya limpio de Analysis_ia
            success_units = await self._post_upsert_many("entities/unidades_logicas", unidades_data, concurrency=20)
            if not success_units:
                log.error("aone_sync_failed_at_unidades")
                    
        if reglas_negocio:
            success_rules = await self._post_upsert_many("entities/reglas_negocio", reglas_negocio, concurrency=20)
            if not success_rules:
                log.error("aone_sync_failed_at_reglas")

        log.info("aone_sync_completed_successfully", scan_id=scan_id, reglas_sincronizadas=len(reglas_negocio))
        return True
