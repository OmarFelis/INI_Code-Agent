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

    # --- Security API ---
    api_secret_token: str = Field(
        default="local-dev-token",
        description="Secret Bearer Token to access the API",
    )

    # --- Security SCM ---
    allowed_git_domains: str = Field(
        default="github.com,bitbucket.org",
        description="Comma-separated list of allowed domains for repo_url",
    )
    git_username: str | None = Field(
        default=None,
        description="Username for Git cloning of private repositories",
    )
    git_token: str | None = Field(
        default=None,
        description="App Password / Access Token for Git cloning",
    )

    # --- Pipeline V2 ---
    parallel_workers_ast: int = Field(
        default=10,
        description="Max concurrent workers for AST extraction (Pass 1)",
    )
    parallel_workers_llm: int = Field(
        default=5,
        description="Max concurrent workers for LLM enrichment (Pass 2)",
    )
    enable_context_enrichment: bool = Field(
        default=True,
        description="Enable context-aware LLM prompts with dependency graph",
    )
    context_max_neighbors: int = Field(
        default=5,
        description="Max neighbor files to include in LLM context",
    )

    # --- LLM Cache ---
    enable_llm_cache: bool = Field(
        default=True,
        description="Enable SQLite-backed cache for LLM responses",
    )
    llm_cache_ttl_days: int = Field(
        default=30,
        description="Time-to-live for cached LLM responses in days",
    )

    # --- Semgrep Security ---
    enable_semgrep_scan: bool = Field(
        default=False,
        description="Enable Semgrep OWASP security scanning (requires semgrep CLI)",
    )
    semgrep_timeout_seconds: int = Field(
        default=120,
        description="Timeout for Semgrep subprocess execution",
    )

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}


# Singleton
settings = Settings()
