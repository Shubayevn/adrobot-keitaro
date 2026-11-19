from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore", env_ignore_empty=True
    )

    # --- Keitaro ---
    # Адрес трекера без /admin_api/v1, например https://tracker.example.com
    keitaro_url: str = "http://127.0.0.1:8081"
    keitaro_api_key: str = "fake-key"
    keitaro_timeout: float = 20.0

    # Значения по умолчанию для «создаватора» (id из Keitaro). Пусто — выбрать в форме.
    keitaro_default_domain_id: int | None = None
    keitaro_default_group_id: int | None = None
    keitaro_default_traffic_source_id: int | None = None

    # Как собирается поток «гео -> гугл». Значения можно сверить: python -m tools.check_keitaro
    redirect_url: str = "https://google.com"
    redirect_action_type: str = "http"
    country_filter_name: str = "country"
    # Поток с офферами: схема «лендинги и офферы» без лендинга
    offers_stream_schema: str = "landings"
    offers_stream_action_type: str = "http"

    # --- База ---
    database_url: str = "sqlite:///./adrobot.db"

    # Кэш списка офферов для автокомплита, секунд
    offers_cache_ttl: int = 60


@lru_cache
def get_settings() -> Settings:
    return Settings()
