"""
Code-Agent — Configuration module.
Loads settings from environment variables / .env file.
"""

from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # --- Database ---
    database_url: str = Field(
        default="postgresql+asyncpg://codeagent:codeagent@localhost:5432/codeagent_db",
        description="SQLAlchemy async database URL",
    )

    # --- A-ONE ---
    aone_base_url: str = Field(
        default="https://lrxgmddycqvq3ql6vqgct3p5za0ityil.lambda-url.us-east-1.on.aws/alignetone_dev_v2",
        description="A-ONE backend base URL for entity endpoints",
    )

    # --- AWS ---
    aws_default_region: str = Field(default="us-east-1")
    aws_profile: str | None = Field(default=None)

    # --- API Server ---
    api_host: str = Field(default="0.0.0.0")
    api_port: int = Field(default=8000)
    log_level: str = Field(default="INFO")

    # --- App ---
    app_name: str = Field(default="Code-Agent")
    app_version: str = Field(default="1.0.0")

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}


# Singleton
settings = Settings()
