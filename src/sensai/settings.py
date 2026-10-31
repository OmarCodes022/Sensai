"""Configuration from the environment and .env. Real env vars win over .env."""
import os

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", frozen=True)

    host: str = Field("http://localhost:11434", validation_alias="OLLAMA_HOST")
    ssh_host: str | None = Field(None, validation_alias="SENSAI_SSH_HOST")
    model: str | None = Field(None, validation_alias="SENSAI_MODEL")
    # None selects the packaged default prompt (sensai/chat/system_prompt.txt).
    prompt_path: str | None = Field(None, validation_alias="SENSAI_PROMPT")
    persona: str | None = Field(None, validation_alias="SENSAI_PERSONA")
    personas_file: str | None = Field(None, validation_alias="SENSAI_PERSONAS_FILE")
    timeout: float = Field(60.0, gt=0, allow_inf_nan=False, validation_alias="SENSAI_TIMEOUT")
    context_length: int | None = Field(None, gt=0, validation_alias="SENSAI_CONTEXT_LENGTH")
    operation_timeout: float = Field(120.0, gt=0, allow_inf_nan=False,
                                     validation_alias="SENSAI_OPERATION_TIMEOUT")
    db_path: str | None = Field(None, validation_alias="SENSAI_DB")
    creator: str = Field("default", validation_alias="SENSAI_CREATOR")
    profile_file: str | None = Field(None, validation_alias="SENSAI_PROFILE_FILE")
    # Files copied into each run_python folder. Unset: ./data when that folder exists (the
    # placeholder in the repository); set but empty: none.
    data_dir: str | None = Field(default_factory=lambda: "data" if os.path.isdir("data") else None,
                                 validation_alias="SENSAI_DATA_DIR")
    test_model: str = Field("gemma3:1b", validation_alias="SENSAI_TEST_MODEL")
    # Brand documents searched by the model. Default ./data/docs (created by /add); empty switches it off.
    docs_dir: str | None = Field("data/docs", validation_alias="SENSAI_DOCS")
    embed_model: str = Field("nomic-embed-text", validation_alias="SENSAI_EMBED_MODEL")
    # Document search mode: advanced (filter, model rerank, drop weak matches; R2) or basic (closest chunks; R1).
    rag_mode: str = Field("advanced", pattern="^(advanced|basic)$", validation_alias="SENSAI_RAG")
    # Guardrails (EV2): extra rules, and the brand file whose approved claims replies may use.
    campaigns_dir: str = Field("campaigns", validation_alias="SENSAI_CAMPAIGNS_DIR")  # The weekly documents (M4).
    exports_dir: str = Field("exports", validation_alias="SENSAI_EXPORTS_DIR")  # Private JSON/Markdown exports (X3).
    # Scheduling (X5): the tasks file the web page runs (unset: schedule.local.json if it exists) and the drafts folder.
    schedule_file: str | None = Field(default_factory=lambda: "schedule.local.json" if os.path.isfile("schedule.local.json") else None,
                                      validation_alias="SENSAI_SCHEDULE_FILE")
    drafts_dir: str = Field("drafts", validation_alias="SENSAI_DRAFTS_DIR")
    # Web search (T3): brave (needs the key), duckduckgo (no key) or off; default brave when a key is set.
    search_provider: str | None = Field(None, validation_alias="SENSAI_SEARCH_PROVIDER")
    search_api_key: str | None = Field(None, validation_alias="SENSAI_SEARCH_API_KEY")
    guardrails_file: str | None = Field(None, validation_alias="SENSAI_GUARDRAILS_FILE")
    brand_file: str | None = Field(default_factory=lambda: "data/brand.json" if os.path.isfile("data/brand.json") else None,
                                   validation_alias="SENSAI_BRAND_FILE")
    mcp_config: str = Field("mcp.json", validation_alias="SENSAI_MCP_CONFIG")
