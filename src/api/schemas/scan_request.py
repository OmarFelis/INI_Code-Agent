"""
Code-Agent — API Request schemas.
"""

from pydantic import BaseModel, Field


class ScanRequest(BaseModel):
    """POST /api/v1/scan request body."""

    project_path: str | None = Field(
        default=None,
        description="Ruta local al repositorio del microservicio",
        examples=["C:/payment-service-charges"],
    )
    branch: str = Field(
        default="main",
        description="Rama del repositorio a analizar",
    )
    activo_id: str = Field(
        ...,
        description="UUID del activo en infra.activos",
        examples=["01961234-0000-7000-8000-000000000001"],
    )
    aplicacion_id: str = Field(
        ...,
        description="UUID de la aplicación en producto.aplicaciones",
        examples=["01961234-0000-7000-8000-000000000001"],
    )
    microservice_name: str = Field(
        ...,
        description="Nombre legible del microservicio",
        examples=["ACS"],
    )
    repo_url: str | None = Field(
        default=None,
        description="URL del repositorio Git (futuro — si se provee, se clona en vez de usar project_path)",
    )

class FunctionToEnrich(BaseModel):
    nombre: str = Field(..., description="Nombre de la función a enriquecer (ej. _evaluate_autenticacion_rules)")
    archivo: str = Field(..., description="Nombre base del archivo de la unidad lógica")

class EnrichmentRequest(BaseModel):
    funciones: list[FunctionToEnrich] = Field(
        ..., 
        description="Lista de funciones seleccionadas del escaneo previo para enviar al LLM"
    )


class BatchScanRequest(BaseModel):
    """POST /api/v1/scan/batch request body."""

    scans: list[ScanRequest] = Field(
        ...,
        description="Lista de scan requests a ejecutar en batch",
        min_length=1,
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "scans": [
                    {
                        "project_path": None,
                        "branch": "main",
                        "activo_id": "01961234-0000-7000-8000-000000000001",
                        "aplicacion_id": "01961234-0000-7000-8000-000000000002",
                        "microservice_name": "payment-service",
                        "repo_url": "https://bitbucket.org/org/payment-service.git"
                    },
                    {
                        "project_path": None,
                        "branch": "main",
                        "activo_id": "01961234-0000-7000-8000-000000000003",
                        "aplicacion_id": "01961234-0000-7000-8000-000000000004",
                        "microservice_name": "auth-service",
                        "repo_url": "https://bitbucket.org/org/auth-service.git"
                    }
                ]
            }
        }
    }

