import structlog
from fastapi import Request, HTTPException, Security
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from src.config import settings

logger = structlog.get_logger()
security = HTTPBearer()

def verify_api_token(credentials: HTTPAuthorizationCredentials = Security(security)):
    """
    Dependency to verify the Bearer token against API_SECRET_TOKEN.
    """
    if credentials.scheme != "Bearer":
        logger.warning("auth_invalid_scheme", scheme=credentials.scheme)
        raise HTTPException(
            status_code=401,
            detail="Invalid authentication scheme.",
            headers={"WWW-Authenticate": "Bearer"},
        )
        
    if credentials.credentials != settings.api_secret_token:
        logger.warning("auth_invalid_token")
        raise HTTPException(
            status_code=401,
            detail="Invalid or expired token.",
            headers={"WWW-Authenticate": "Bearer"},
        )
        
    return credentials.credentials
