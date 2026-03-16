"""
Tests para verificar la resolución de bugs documentados en BUGS_Y_MEJORAS.md.
Ejecutar con: pytest tests/test_bug_fixes.py -v
"""
import json
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest

from src.models.domain import ArchivoFuente, UnidadLogica


# ══════════════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════════════

def _make_archivo(nombre: str, n_funciones: int = 2, n_clases: int = 1) -> ArchivoFuente:
    return ArchivoFuente(
        id=str(uuid.uuid4()),
        activo_id="activo-test",
        aplicacion_id="app-test",
        nombre=nombre,
        total_funciones=n_funciones,
        total_clases=n_clases,
    )


def _make_unidad(nombre: str, archivo: ArchivoFuente, tipo: str = "FUNCION") -> UnidadLogica:
    return UnidadLogica(
        id=str(uuid.uuid4()),
        archivo_id=archivo.id,
        activo_id="activo-test",
        aplicacion_id="app-test",
        nombre=nombre,
        tipo=tipo,
    )


def _make_pipeline_result(archivos, unidades):
    """Crea un PipelineResult mínimo para tests de _build_results."""
    from src.core.analyzers.pipeline import PipelineResult
    r = PipelineResult()
    r.archivos = archivos
    r.unidades = unidades
    r.processed_files = len(archivos)
    r.score_general = 75.0
    r.nivel_riesgo = "LOW"
    return r


# ══════════════════════════════════════════════════════════════════════
# BUG-01 — Loop de persistencia de unidades mal anidado
# ══════════════════════════════════════════════════════════════════════

class TestBug01LoopPersistencia:
    """
    Verifica que cada unidad se persiste exactamente 1 vez,
    no N veces (donde N = número de archivos).
    """

    @pytest.mark.asyncio
    async def test_cada_unidad_se_persiste_exactamente_una_vez(self):
        archivo_a = _make_archivo("archivo_a.py")
        archivo_b = _make_archivo("archivo_b.py")
        unidad_a1 = _make_unidad("funcion_a1", archivo_a)
        unidad_a2 = _make_unidad("funcion_a2", archivo_a)
        unidad_b1 = _make_unidad("funcion_b1", archivo_b)

        archivos = [archivo_a, archivo_b]
        unidades = [unidad_a1, unidad_a2, unidad_b1]

        mock_client = MagicMock()
        mock_client.post_archivo_fuente = AsyncMock(return_value={"id": str(uuid.uuid4())})
        mock_client.post_unidad_logica = AsyncMock(return_value={"id": str(uuid.uuid4())})

        from src.core.analyzers.pipeline import run
        with patch("src.core.analyzers.pipeline.ProjectAnalyzerService") as mock_svc, \
             patch("src.core.analyzers.pipeline.worker_pool.run_parallel_extraction") as mock_wp, \
             patch("src.core.analyzers.pipeline.ContextBuilder"), \
             patch("src.core.analyzers.pipeline._get_commit_hash", return_value="abc123"):

            mock_svc.return_value.analyze_project.return_value = MagicMock(
                total_files=2, total_lines=100, files=[], languages={}
            )
            mock_wp.return_value = (archivos, unidades, [])

            await run(
                project_path="/fake/path",
                activo_id="activo-test",
                aplicacion_id="app-test",
                microservice_name="test",
                aone_client=mock_client,
            )

        # Cada unidad debe haberse persistido exactamente 1 vez
        assert mock_client.post_unidad_logica.call_count == 3, (
            f"Se esperaban 3 llamadas (1 por unidad), "
            f"pero se hicieron {mock_client.post_unidad_logica.call_count}"
        )

    @pytest.mark.asyncio
    async def test_unidades_se_asocian_al_archivo_correcto(self):
        """Las unidades de archivo_a no deben persistirse cuando se procesa archivo_b."""
        archivo_a = _make_archivo("archivo_a.py")
        archivo_b = _make_archivo("archivo_b.py")
        unidad_a = _make_unidad("solo_en_a", archivo_a)
        unidad_b = _make_unidad("solo_en_b", archivo_b)

        llamadas_por_unidad = []

        async def mock_post_unidad(unidad):
            llamadas_por_unidad.append(unidad.nombre)
            return {"id": str(uuid.uuid4())}

        mock_client = MagicMock()
        mock_client.post_archivo_fuente = AsyncMock(return_value={"id": str(uuid.uuid4())})
        mock_client.post_unidad_logica = mock_post_unidad

        from src.core.analyzers.pipeline import run
        with patch("src.core.analyzers.pipeline.ProjectAnalyzerService") as mock_svc, \
             patch("src.core.analyzers.pipeline.worker_pool.run_parallel_extraction") as mock_wp, \
             patch("src.core.analyzers.pipeline.ContextBuilder"), \
             patch("src.core.analyzers.pipeline._get_commit_hash", return_value="abc123"):

            mock_svc.return_value.analyze_project.return_value = MagicMock(
                total_files=2, total_lines=50, files=[], languages={}
            )
            mock_wp.return_value = ([archivo_a, archivo_b], [unidad_a, unidad_b], [])

            await run(
                project_path="/fake/path",
                activo_id="activo-test",
                aplicacion_id="app-test",
                microservice_name="test",
                aone_client=mock_client,
            )

        assert llamadas_por_unidad.count("solo_en_a") == 1
        assert llamadas_por_unidad.count("solo_en_b") == 1


# ══════════════════════════════════════════════════════════════════════
# BUG-03 — Solo se guarda la última regla de negocio
# ══════════════════════════════════════════════════════════════════════

class TestBug03ReglasDenegocio:
    """
    Verifica que todas las reglas de negocio de una unidad se persisten,
    no solo la última.
    """

    @pytest.mark.asyncio
    async def test_todas_las_reglas_se_agregan_a_la_lista(self):
        from src.core.integration.aone_client import AOneSyncClient

        reglas = [
            {"descripcion": "Regla 1", "codigo_relacionado": "if x > 0:"},
            {"descripcion": "Regla 2", "codigo_relacionado": "if y < 10:"},
            {"descripcion": "Regla 3", "codigo_relacionado": "if z == 0:"},
        ]

        unidad_id = str(uuid.uuid4())
        archivo_id = str(uuid.uuid4())
        scan_id = str(uuid.uuid4())

        job_results = {
            "escaneo": {
                "id": scan_id,
                "activo_id": "activo-test",
                "aplicacion_id": "app-test",
                "status": "COMPLETED",
                "archivos_total": 1,
            },
            "archivos_fuente": [
                {"id": archivo_id, "nombre": "handler.py", "escaneado_en": "2025-01-01"}
            ],
            "unidades_logicas": [
                {
                    "id": unidad_id,
                    "nombre": "mi_funcion",
                    "tipo": "FUNCION",
                    "archivo": "handler.py",
                    "analisis_ia": {
                        "resumen_funcional": "Hace algo",
                        "modifica_estado": False,
                        "reglas_de_negocio": reglas,
                    },
                }
            ],
        }

        reglas_enviadas = []

        client = AOneSyncClient.__new__(AOneSyncClient)
        client.base_url = "http://fake"
        client.client = MagicMock()

        async def mock_post_upsert(endpoint, payload):
            if endpoint == "entities/reglas_negocio":
                reglas_enviadas.append(payload)
            return True

        async def mock_post_upsert_many(endpoint, items, concurrency=15):
            if endpoint == "entities/reglas_negocio":
                reglas_enviadas.extend(items)
            return True

        client._post_upsert = mock_post_upsert
        client._post_upsert_many = mock_post_upsert_many

        await client.sync_scan_results(job_results)

        assert len(reglas_enviadas) == 3, (
            f"Se esperaban 3 reglas persistidas, pero se persistieron {len(reglas_enviadas)}"
        )
        descripciones = [r["descripcion"] for r in reglas_enviadas]
        assert "Regla 1" in descripciones
        assert "Regla 2" in descripciones
        assert "Regla 3" in descripciones

    @pytest.mark.asyncio
    async def test_regla_como_string_se_maneja_correctamente(self):
        """Reglas que vienen como string (no dict) también deben procesarse."""
        from src.core.integration.aone_client import AOneSyncClient

        scan_id = str(uuid.uuid4())
        unidad_id = str(uuid.uuid4())
        archivo_id = str(uuid.uuid4())

        job_results = {
            "escaneo": {"id": scan_id, "activo_id": "a", "aplicacion_id": "b", "status": "COMPLETED", "archivos_total": 1},
            "archivos_fuente": [{"id": archivo_id, "nombre": "f.py"}],
            "unidades_logicas": [{
                "id": unidad_id,
                "nombre": "fn",
                "tipo": "FUNCION",
                "archivo": "f.py",
                "analisis_ia": {
                    "resumen_funcional": "test",
                    "modifica_estado": False,
                    "reglas_de_negocio": ["regla como string simple"],
                },
            }],
        }

        reglas_enviadas = []
        client = AOneSyncClient.__new__(AOneSyncClient)
        client.base_url = "http://fake"
        client.client = MagicMock()
        client._post_upsert = AsyncMock(return_value=True)

        async def mock_many(endpoint, items, concurrency=15):
            if endpoint == "entities/reglas_negocio":
                reglas_enviadas.extend(items)
            return True

        client._post_upsert_many = mock_many

        await client.sync_scan_results(job_results)

        assert len(reglas_enviadas) == 1
        assert reglas_enviadas[0]["descripcion"] == "regla como string simple"
        assert reglas_enviadas[0]["codigo_relacionado"] is None


# ══════════════════════════════════════════════════════════════════════
# BUG-04 — Status IN_PROGRESS no existe en el enum
# ══════════════════════════════════════════════════════════════════════

class TestBug04StatusRunning:
    """Verifica que el background task usa RUNNING y no IN_PROGRESS."""

    def test_status_running_existe_en_enum(self):
        from src.models.domain import ScanStatus
        assert ScanStatus.RUNNING.value == "RUNNING"

    def test_status_in_progress_no_existe_en_enum(self):
        from src.models.domain import ScanStatus
        valores = [s.value for s in ScanStatus]
        assert "IN_PROGRESS" not in valores, "IN_PROGRESS no debe existir en ScanStatus"

    def test_scan_py_no_usa_in_progress(self):
        """Verifica a nivel de código fuente que no queda ningún IN_PROGRESS."""
        import ast
        with open("src/api/routes/scan.py", "r", encoding="utf-8") as f:
            source = f.read()
        assert "IN_PROGRESS" not in source, (
            "El archivo scan.py todavía contiene 'IN_PROGRESS'"
        )


# ══════════════════════════════════════════════════════════════════════
# BUG-05 — datetime.utcnow() deprecado
# ══════════════════════════════════════════════════════════════════════

class TestBug05DatetimeTimezone:
    """Verifica que no se usa datetime.utcnow() en repository.py."""

    def test_repository_no_usa_utcnow(self):
        with open("src/db/repository.py", "r", encoding="utf-8") as f:
            source = f.read()
        assert "utcnow()" not in source, (
            "repository.py todavía usa datetime.utcnow() deprecado"
        )

    def test_repository_usa_timezone_utc(self):
        with open("src/db/repository.py", "r", encoding="utf-8") as f:
            source = f.read()
        assert "timezone.utc" in source

    @pytest.mark.asyncio
    async def test_started_at_tiene_timezone(self):
        """El campo started_at debe ser timezone-aware al actualizar a RUNNING."""
        from src.db import repository
        from unittest.mock import AsyncMock, MagicMock

        mock_session = MagicMock()
        mock_session.execute = AsyncMock()

        captured_values = {}

        async def capture_execute(stmt):
            # Extraer los valores del UPDATE statement
            if hasattr(stmt, "_values"):
                captured_values.update(stmt._values)

        mock_session.execute = capture_execute

        job_id = uuid.uuid4()

        # Capturamos directamente el valor que se construye
        with patch("src.db.repository.datetime") as mock_dt:
            aware_dt = datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
            mock_dt.now.return_value = aware_dt
            mock_dt.now.side_effect = lambda tz=None: aware_dt

            await repository.update_scan_job_status(mock_session, job_id, status="RUNNING")

        # Verificar que se llamó con timezone.utc
        mock_dt.now.assert_called_with(timezone.utc)


# ══════════════════════════════════════════════════════════════════════
# BUG-06 — Asignación de archivo a unidades por FK real
# ══════════════════════════════════════════════════════════════════════

class TestBug06AsignacionArchivo:
    """
    Verifica que _build_results asigna el archivo correcto a cada unidad
    usando archivo_id FK, no conteo secuencial.
    """

    def test_unidades_asignadas_por_archivo_id(self):
        from src.api.routes.scan import _build_results

        archivo_a = _make_archivo("modulo_a.py", n_funciones=1, n_clases=0)
        archivo_b = _make_archivo("modulo_b.py", n_funciones=1, n_clases=0)

        # Unidades en orden inverso al de archivos — el conteo secuencial fallaría
        unidad_b = _make_unidad("funcion_b", archivo_b)
        unidad_a = _make_unidad("funcion_a", archivo_a)

        result = _make_pipeline_result(
            archivos=[archivo_a, archivo_b],
            unidades=[unidad_b, unidad_a],  # orden invertido intencionalmente
        )

        output = _build_results(result)
        unidades_out = output["unidades_logicas"]

        archivo_por_nombre = {u["nombre"]: u["archivo"] for u in unidades_out}
        assert archivo_por_nombre["funcion_b"] == "modulo_b.py", (
            f"funcion_b debería estar en modulo_b.py, está en {archivo_por_nombre['funcion_b']}"
        )
        assert archivo_por_nombre["funcion_a"] == "modulo_a.py", (
            f"funcion_a debería estar en modulo_a.py, está en {archivo_por_nombre['funcion_a']}"
        )

    def test_unidad_sin_archivo_matching_queda_como_unknown(self):
        from src.api.routes.scan import _build_results

        archivo = _make_archivo("real.py")
        unidad_huerfana = UnidadLogica(
            id=str(uuid.uuid4()),
            archivo_id="id-que-no-existe",  # FK rota
            activo_id="a",
            aplicacion_id="b",
            nombre="funcion_huerfana",
            tipo="FUNCION",
        )

        result = _make_pipeline_result(archivos=[archivo], unidades=[unidad_huerfana])
        output = _build_results(result)

        assert output["unidades_logicas"][0]["archivo"] == "unknown"


# ══════════════════════════════════════════════════════════════════════
# BUG-07 — escaneado_en sin timezone
# ══════════════════════════════════════════════════════════════════════

class TestBug07EscaneadoEnTimezone:
    """Verifica que escaneado_en en el escaneo incluye timezone UTC."""

    def test_escaneado_en_tiene_timezone(self):
        from src.api.routes.scan import _build_results

        archivo = _make_archivo("app.py")
        result = _make_pipeline_result(archivos=[archivo], unidades=[])

        output = _build_results(result)
        escaneado_en = output["escaneo"]["escaneado_en"]

        # Un datetime naive no tiene +00:00 ni Z
        assert "+" in escaneado_en or escaneado_en.endswith("Z"), (
            f"escaneado_en no tiene timezone: {escaneado_en}"
        )

    def test_escaneado_en_es_parseable_con_timezone(self):
        from src.api.routes.scan import _build_results

        archivo = _make_archivo("app.py")
        result = _make_pipeline_result(archivos=[archivo], unidades=[])
        output = _build_results(result)

        dt = datetime.fromisoformat(output["escaneo"]["escaneado_en"])
        assert dt.tzinfo is not None, "El datetime parseado no tiene tzinfo"


# ══════════════════════════════════════════════════════════════════════
# BUG-08 — Credenciales AWS hardcodeadas
# ══════════════════════════════════════════════════════════════════════

class TestBug08CredencialesAWS:
    """Verifica que las credenciales AWS no están hardcodeadas en llm_enricher."""

    def test_profile_name_no_hardcodeado(self):
        with open("src/core/enricher/llm_enricher.py", "r", encoding="utf-8") as f:
            source = f.read()
        assert "AmazonBedrockLimitedAccess" not in source, (
            "El nombre de perfil AWS sigue hardcodeado en llm_enricher.py"
        )

    def test_region_viene_de_settings(self):
        with open("src/core/enricher/llm_enricher.py", "r", encoding="utf-8") as f:
            source = f.read()
        assert "settings.aws_default_region" in source

    def test_model_id_viene_de_settings(self):
        with open("src/core/enricher/llm_enricher.py", "r", encoding="utf-8") as f:
            source = f.read()
        assert "settings.bedrock_model_id" in source

    def test_bedrock_model_id_existe_en_settings(self):
        from src.config import Settings
        s = Settings()
        assert hasattr(s, "bedrock_model_id")
        assert s.bedrock_model_id  # no vacío

    def test_region_y_model_leen_de_settings_en_runtime(self):
        from src.core.enricher import llm_enricher
        from src.config import settings
        assert llm_enricher.REGION == settings.aws_default_region
        assert llm_enricher.MODEL_ID == settings.bedrock_model_id


# ══════════════════════════════════════════════════════════════════════
# BUG-09 — commit_hash null en scans remotos
# ══════════════════════════════════════════════════════════════════════

class TestBug09CommitHash:
    """
    Verifica que _build_results toma el primer commit_hash no-null,
    y que el fallback post-move funciona.
    """

    def test_build_results_toma_primer_hash_no_null(self):
        from src.api.routes.scan import _build_results

        archivo_sin_hash = _make_archivo("a.py")
        archivo_sin_hash.commit_hash = None

        archivo_con_hash = _make_archivo("b.py")
        archivo_con_hash.commit_hash = "abc123def456"

        result = _make_pipeline_result(
            archivos=[archivo_sin_hash, archivo_con_hash],
            unidades=[],
        )
        output = _build_results(result)
        assert output["escaneo"]["commit_hash"] == "abc123def456"

    def test_build_results_retorna_none_si_todos_null(self):
        from src.api.routes.scan import _build_results

        archivo = _make_archivo("a.py")
        archivo.commit_hash = None

        result = _make_pipeline_result(archivos=[archivo], unidades=[])
        output = _build_results(result)
        assert output["escaneo"]["commit_hash"] is None

    @pytest.mark.asyncio
    async def test_fallback_commit_hash_post_move(self):
        """Si todos los archivos tienen commit_hash=None, se re-captura tras el move."""
        from src.api.routes.scan import _run_scan_background_task
        from src.api.schemas.scan_request import ScanRequest

        job_id = uuid.uuid4()
        request = ScanRequest(
            activo_id="activo-test",
            aplicacion_id="app-test",
            microservice_name="test-service",
            project_path="/fake/path",  # requerido por el schema
            repo_url="https://github.com/fake/repo",
        )

        archivo = _make_archivo("handler.py")
        archivo.commit_hash = None  # Simula clone sin hash

        mock_result = _make_pipeline_result(archivos=[archivo], unidades=[])

        mock_session = AsyncMock()
        mock_session.commit = AsyncMock()
        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)

        with patch("src.api.routes.scan.repository") as mock_repo, \
             patch("src.api.routes.scan.async_session_factory", return_value=mock_ctx), \
             patch("src.core.scm.scm_adapter.clone_repository", new_callable=AsyncMock), \
             patch("src.core.analyzers.pipeline.run", new_callable=AsyncMock, return_value=mock_result), \
             patch("src.core.analyzers.pipeline._get_commit_hash", return_value="fallback_hash_xyz"), \
             patch("src.api.routes.scan.AOneSyncClient") as mock_sync, \
             patch("os.path.exists", return_value=True), \
             patch("os.makedirs"), \
             patch("shutil.move"):

            mock_repo.update_scan_job_status = AsyncMock()
            mock_sync_instance = AsyncMock()
            mock_sync_instance.sync_scan_results = AsyncMock(return_value=True)
            mock_sync_instance.close = AsyncMock()
            mock_sync.return_value = mock_sync_instance

            await _run_scan_background_task(job_id, request)

        # El archivo debe tener el hash del fallback
        assert archivo.commit_hash == "fallback_hash_xyz"


# ══════════════════════════════════════════════════════════════════════
# MEJ-06 — Mutación del dict en sync (doble serialización)
# ══════════════════════════════════════════════════════════════════════

class TestMej06IdempotenciaSyncAnalisisIa:
    """
    Verifica que llamar sync_scan_results dos veces no corrompe analisis_ia
    (no debe hacer json.dumps de un string que ya es string).
    """

    @pytest.mark.asyncio
    async def test_analisis_ia_no_se_doble_serializa(self):
        from src.core.integration.aone_client import AOneSyncClient

        scan_id = str(uuid.uuid4())
        archivo_id = str(uuid.uuid4())
        ia_original = {"resumen_archivo": "Hace cosas", "observaciones": []}

        job_results = {
            "escaneo": {"id": scan_id, "activo_id": "a", "aplicacion_id": "b", "status": "COMPLETED", "archivos_total": 1},
            "archivos_fuente": [
                {"id": archivo_id, "nombre": "handler.py", "analisis_ia": ia_original}
            ],
            "unidades_logicas": [],
        }

        client = AOneSyncClient.__new__(AOneSyncClient)
        client.base_url = "http://fake"
        client.client = MagicMock()
        client._post_upsert = AsyncMock(return_value=True)
        client._post_upsert_many = AsyncMock(return_value=True)

        # Primera llamada
        await client.sync_scan_results(job_results)
        valor_tras_primera = job_results["archivos_fuente"][0]["analisis_ia"]

        # Segunda llamada (retry)
        await client.sync_scan_results(job_results)
        valor_tras_segunda = job_results["archivos_fuente"][0]["analisis_ia"]

        # Ambas deben ser string JSON (serializado una sola vez)
        assert isinstance(valor_tras_primera, str), "Tras la 1ª llamada debe ser string"
        assert isinstance(valor_tras_segunda, str), "Tras la 2ª llamada debe seguir siendo string"

        # El contenido no debe estar doblemente serializado
        parsed = json.loads(valor_tras_segunda)
        assert isinstance(parsed, dict), (
            "El valor está doblemente serializado (json dentro de json)"
        )
        assert parsed["resumen_archivo"] == "Hace cosas"


# ══════════════════════════════════════════════════════════════════════
# MEJ-10 — Path Traversal en project_path
# ══════════════════════════════════════════════════════════════════════

class TestMej10PathTraversal:
    """
    Verifica que el endpoint rechaza project_path fuera de los directorios permitidos.
    """

    @pytest.fixture
    def auth_headers(self):
        from src.config import settings
        return {"Authorization": f"Bearer {settings.api_secret_token}"}

    @pytest.mark.asyncio
    async def test_path_fuera_de_whitelist_retorna_403(self, auth_headers):
        from httpx import AsyncClient, ASGITransport
        from src.api.main import app

        payload = {
            "activo_id": "activo-test",
            "aplicacion_id": "app-test",
            "microservice_name": "test",
            "project_path": "/etc/passwd",
        }

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/api/v1/scan",
                json=payload,
                headers=auth_headers,
            )

        assert response.status_code == 403, (
            f"Se esperaba 403 para path traversal, se obtuvo {response.status_code}"
        )

    @pytest.mark.asyncio
    async def test_path_raiz_retorna_403(self, auth_headers):
        from httpx import AsyncClient, ASGITransport
        from src.api.main import app

        payload = {
            "activo_id": "activo-test",
            "aplicacion_id": "app-test",
            "microservice_name": "test",
            "project_path": "/",
        }

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/api/v1/scan",
                json=payload,
                headers=auth_headers,
            )

        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_path_traversal_con_dotdot_retorna_403(self, auth_headers):
        from httpx import AsyncClient, ASGITransport
        from src.api.main import app

        payload = {
            "activo_id": "activo-test",
            "aplicacion_id": "app-test",
            "microservice_name": "test",
            "project_path": "../../etc",
        }

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/api/v1/scan",
                json=payload,
                headers=auth_headers,
            )

        assert response.status_code == 403
