"""Configuration from the environment and .env. Real env vars win over .env."""
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", frozen=True)

    host: str = Field("http://localhost:11434", validation_alias="OLLAMA_HOST")
    model: str | None = Field(None, validation_alias="SENSAI_MODEL")
    prompt_path: str = Field("prompts/system.txt", validation_alias="SENSAI_PROMPT")
    timeout: float = Field(60.0, gt=0, validation_alias="SENSAI_TIMEOUT")
    test_model: str = Field("gemma3:1b", validation_alias="SENSAI_TEST_MODEL")
