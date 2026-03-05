"""
Code-Agent — A-ONE HTTP Client.
Handles communication with A-ONE entity endpoints for persisting scan results.
"""

import json

import httpx
import structlog

from src.config import settings
from src.models.domain import ArchivoFuente, UnidadLogica, Escaneo

logger = structlog.get_logger()

# Base URL from settings
AONE_BASE_URL = settings.aone_base_url


class AOneClient:
    """HTTP client for A-ONE entity endpoints."""

    def __init__(self, base_url: str = AONE_BASE_URL):
        self.base_url = base_url.rstrip("/")
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=30.0)
        return self._client

    async def close(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    # --- archivos_fuente ---

    async def post_archivo_fuente(self, archivo: ArchivoFuente) -> dict:
        """POST a new archivo_fuente record to A-ONE."""
        client = await self._get_client()
        url = f"{self.base_url}/entities/archivos_fuente"
        payload = archivo.model_dump(exclude_none=True)
        logger.debug("aone_post_archivo", url=url, nombre=archivo.nombre)

        resp = await client.post(url, json=payload)
        resp.raise_for_status()
        return resp.json()

    # --- unidades_logicas ---

    async def post_unidad_logica(self, unidad: UnidadLogica) -> dict:
        """POST a new unidad_logica record to A-ONE."""
        client = await self._get_client()
        url = f"{self.base_url}/entities/unidades_logicas"
        payload = unidad.model_dump(exclude_none=True)
        logger.debug("aone_post_unidad", url=url, nombre=unidad.nombre)

        resp = await client.post(url, json=payload)
        resp.raise_for_status()
        return resp.json()

    # --- escaneos ---

    async def post_escaneo(self, escaneo: Escaneo) -> dict:
        """POST a new escaneo record to A-ONE."""
        client = await self._get_client()
        url = f"{self.base_url}/entities/escaneos"
        payload = escaneo.model_dump(exclude_none=True)
        logger.debug("aone_post_escaneo", url=url, activo_id=escaneo.activo_id)

        resp = await client.post(url, json=payload)
        resp.raise_for_status()
        return resp.json()

    async def get_escaneos_by_activo(self, activo_id: str) -> list[dict]:
        """GET escaneos filtered by activo_id."""
        client = await self._get_client()
        url = f"{self.base_url}/entities/escaneos"
        resp = await client.get(url, params={"activo_id": activo_id})
        resp.raise_for_status()
        return resp.json()


# Singleton
aone_client = AOneClient()
