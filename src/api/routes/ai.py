import structlog
from fastapi import APIRouter, HTTPException

from src.api.schemas.analyze_schema import AnalyzeRequest, AnalyzeResponse, EnrichedFunction
from src.core.enricher.llm_enricher import analyze_functions_batch

logger = structlog.get_logger()
router = APIRouter(prefix="/api/v1/analyze", tags=["analyze"])

@router.post(
    "",
    response_model=AnalyzeResponse,
    summary="Analiza un lote de funciones usando AWS Bedrock (Claude)",
    description="Recibe una lista de funciones con código fuente y devuelve reglas de negocio extraídas mediante IA."
)
async def analyze_functions(request: AnalyzeRequest):
    """
    Endpoint de la Fase 2 (Enriquecimiento Agentic).
    """
    logger.info("analyze_batch_requested", project=request.project_path, funcs_count=len(request.funciones))
    
    if not request.funciones:
        raise HTTPException(status_code=400, detail="La lista de funciones a analizar no puede estar vacía.")
        
    # Convertir los objectos pydantic a dicts para que llm_enricher los use fácilmente
    batch_data = [func.model_dump() for func in request.funciones]
    
    try:
        enriched_results = await analyze_functions_batch(batch_data)
        
        # Mapeamos el output dict nuevamente a Schemas para validación
        response_model_list = []
        for result in enriched_results:
            response_model_list.append(EnrichedFunction(**result))
            
        logger.info("analyze_batch_success", project=request.project_path)
        
        return AnalyzeResponse(
            status="SUCCESS",
            analizadas=len(response_model_list),
            resultados=response_model_list
        )
        
    except Exception as e:
         logger.error("analyze_batch_error", error=str(e))
         raise HTTPException(status_code=500, detail=f"Error al analizar con LLM: {str(e)}")
