# app/core/config.py
import os
from typing import Optional

from dotenv import load_dotenv
from pydantic import BaseModel

load_dotenv()


class Settings(BaseModel):
    db_host: str = os.getenv("DB_HOST")
    db_port: int = int(os.getenv("DB_PORT"))
    db_user: str = os.getenv("POSTGRES_USER")
    db_pass: str = os.getenv("POSTGRES_PASSWORD")
    db_name: str = os.getenv("DB_NAME")
    llm_provider: str = os.getenv("LLM_PROVIDER")
    llm_model: str = os.getenv("LLM_MODEL")
    llm_model_mini: str = os.getenv("LLM_MODEL_MINI")
    persist_dir: str = os.getenv("PERSIST_DIR")
    default_sources: str = os.getenv("DEFAULT_SOURCES")
    allowed_roles: str = os.getenv("ALLOWED_ROLES", "yonetici,ogretmen,ogrenci")

    init_llm_on_startup: bool = os.getenv("INIT_LLM_ON_STARTUP", "true").lower() == "true"
    init_vector_on_startup: bool = os.getenv("INIT_VECTOR_ON_STARTUP", "true").lower() == "true"

    rate_limit_max_requests: int = int(os.getenv("RATE_LIMIT_MAX_REQUESTS", "20"))
    rate_limit_window_seconds: int = int(os.getenv("RATE_LIMIT_WINDOW_SECONDS", "60"))
    max_user_prompt_length: int = int(os.getenv("MAX_USER_PROMPT_LENGTH", "4000"))

    default_tenant_id: str = os.getenv("DEFAULT_TENANT_ID", "pilot")
    # tenant_config_path: Optional[str] = os.getenv("TENANT_CONFIG_PATH")  # Disabled - using fallback config
    
    # CORS settings
    cors_origins: str = os.getenv("CORS_ORIGINS", "*")
    cors_allow_credentials: bool = os.getenv("CORS_ALLOW_CREDENTIALS", "true").lower() == "true"


settings = Settings()
