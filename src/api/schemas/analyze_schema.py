from typing import List, Optional
from pydantic import BaseModel, Field

class FunctionSnippet(BaseModel):
    nombre_funcion: str = Field(..., description="Nombre de la función original")
    componente: str = Field(..., description="Nombre de la clase o módulo padre")
    archivo: str = Field(..., description="Archivo de donde proviene la función")
    lineas: str = Field(..., description="Rango de líneas en el código original")
    codigo_original: str = Field(..., description="El código fuente exacto para pasarle al LLM")
    
class AnalyzeRequest(BaseModel):
    project_path: str = Field(..., description="Project repository path for context logging")
    funciones: List[FunctionSnippet] = Field(..., description="Lista de funciones a enriquecer")

class BusinessRule(BaseModel):
    descripcion: str = Field(..., description="Explicación en lenguaje natural de la regla de negocio")
    codigo_relacionado: str = Field(..., description="El fragmento de código exacto (snippet) que detona esta regla")

class AIAnalysisResult(BaseModel):
    resumen_funcional: str = Field(..., description="Explicación en lenguaje natural")
    modifica_estado: bool = Field(..., description="True si la función altera estado, BD o variables globales")
    reglas_de_negocio: List[BusinessRule] = Field(default_factory=list, description="Lista de reglas identificadas por la IA con su código")
    error: Optional[str] = Field(None, description="Mensaje de error si la IA falló para este ítem")

class EnrichedFunction(BaseModel):
    nombre_funcion: str = Field(...)
    componente: str = Field(...)
    archivo: str = Field(...)
    analisis_ia: AIAnalysisResult = Field(...)

class AnalyzeResponse(BaseModel):
    status: str = Field(..., description="Status string")
    analizadas: int = Field(..., description="Number of functions successfully analyzed")
    resultados: List[EnrichedFunction] = Field(..., description="Los resultados del LLM mapeados a cada función")
