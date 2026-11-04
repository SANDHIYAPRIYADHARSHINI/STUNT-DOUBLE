"""Environment-backed configuration."""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Demo settings; approval cannot be disabled by configuration."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    demo_source_database_url: str = "sqlite:///./data/demo_source.db"
    database_url: str = "sqlite:///./data/demo.db"
    sandbox_database_url_1: str = "sqlite:///./data/sandbox1/sandbox.db"
    sandbox_database_url_2: str = "sqlite:///./data/sandbox2/sandbox.db"
    sandbox_database_url_3: str = "sqlite:///./data/sandbox3/sandbox.db"
    gemma_api_key: str = Field(default="", repr=False)
    openai_api_key: str = Field(default="", repr=False)
    agent_timeout_seconds: int = Field(default=30, gt=0)
    max_affected_rows: int = Field(default=100, gt=0)
    require_human_approval: bool = True


settings = Settings()
