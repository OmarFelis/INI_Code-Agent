"""Quick test: scan Code-Agent's own source code."""
import asyncio
import json
from src.core.analyzers.pipeline import run


async def main():
    result = await run(
        project_path="C:/INI_Code-Agent/src",
        activo_id="test-activo-001",
        aplicacion_id="test-app-001",
        microservice_name="code-agent-self",
        aone_client=None,
    )

    print("=== PIPELINE RESULT ===")
    print(f"Files: {result.total_files} total, {result.processed_files} processed, {len(result.failed_files)} failed")
    print(f"Score: {result.score_general} | Risk: {result.nivel_riesgo}")
    print(f"Archivos: {len(result.archivos)} | Unidades: {len(result.unidades)}")
    print()

    print("--- ARCHIVOS ---")
    for a in result.archivos:
        print(f"  {a.nombre:<35} capa={a.capa:<15} proposito={a.proposito:<12} funcs={a.total_funciones} cls={a.total_clases} loc={a.lineas_codigo}")

    print()
    print("--- UNIDADES (top 15) ---")
    for u in result.unidades[:15]:
        meta = json.loads(u.metadata) if u.metadata else {}
        score = meta.get("overall_score", "-")
        risk = meta.get("risk_level", "-")
        parent = f" (parent: {u.parent_id})" if u.parent_id else ""
        print(f"  {u.tipo:<8} {u.nombre:<35} score={score!s:>6} risk={risk!s:>6} L{u.linea_inicio}-{u.linea_fin}{parent}")

    if result.failed_files:
        print()
        print("--- FAILED FILES ---")
        for f in result.failed_files:
            print(f"  {f['archivo']}: {f['error']}")


if __name__ == "__main__":
    asyncio.run(main())
