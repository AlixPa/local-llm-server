from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="LOCAL_LLM_", env_file=".env")

    db_path: Path = Path("data/local_llm.db")

    @property
    def async_url(self) -> str:
        return f"sqlite+aiosqlite:///{self._prepared_path()}"

    @property
    def sync_url(self) -> str:
        return f"sqlite:///{self._prepared_path()}"

    def _prepared_path(self) -> Path:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        return self.db_path


@lru_cache
def get_settings() -> Settings:
    return Settings()
