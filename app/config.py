from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # anthropic: API da Anthropic (padrão); openrouter: API compatível com OpenAI do OpenRouter.
    llm_provider: Literal["anthropic", "openrouter"] = "anthropic"
    anthropic_api_key: str = ""
    openrouter_api_key: str = ""
    llm_model_main: str = "claude-opus-5-5"
    llm_model_fast: str = "claude-haiku-5-5"

    database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5432/postgres"
    supabase_url: str = ""
    supabase_service_role_key: str = ""
    supabase_key: str = ""  # chave da API; só serve ao backend se for a secreta/service_role

    cors_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:3000"]
    )

    # memory: casos e checkpointer em memória (demo local, testes); postgres: Supabase.
    persistence: Literal["memory", "postgres"] = "memory"
    kg_version: str = "latest"
    demo_mode: bool = False
    enrichment_timeout_s: float = 5
    enable_dev_routes: bool = False
    external_data_mode: Literal["auto", "sql", "rest"] = "auto"
    external_data_cache_ttl_s: float = 30 * 24 * 3600

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: str | list[str]) -> list[str]:
        if isinstance(value, str):
            return [o.strip() for o in value.split(",") if o.strip()]
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
