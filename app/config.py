"""Runtime settings. Secrets come from the environment, never from source."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = (
        "postgresql+asyncpg://harborline:harborline@localhost:5432/harborline"
    )
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    instruction_version: str = "agent_v2"


@lru_cache
def get_settings() -> Settings:
    return Settings()
