from pydantic_settings import BaseSettings, SettingsConfigDict


class OllamaSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="LOCAL_LLM_OLLAMA_", env_file=".env", extra="ignore"
    )

    host: str = "http://localhost:11434"
    num_ctx: int = 32768
