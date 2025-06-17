# mcp_service/app/core/settings.py
# The module is for managing application settings using Pydantic.
# Author: Shibo Li
# Date: 2025-06-16
# Version: 0.1.0

from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional

class Settings(BaseSettings):
    """
    A class to hold all application settings, loaded from an .env file.
    """
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # General Settings
    PROJECT_NAME: str = "MCP Service"
    DEBUG: bool = True

    # LLM Provider Configuration
    LLM_PROVIDER: str = "DEEPSEEK_CHAT"

    DEEPSEEK_CHAT_API_KEY: Optional[str] = None
    DEEPSEEK_CHAT_MODEL: Optional[str] = None
    DEEPSEEK_CHAT_BASE_URL: Optional[str] = None

    CHATGPT_API_KEY: Optional[str] = None
    CHATGPT_MODEL: Optional[str] = None
    CHATGPT_BASE_URL: Optional[str] = None

    CLAUDE_API_KEY: Optional[str] = None
    CLAUDE_MODEL: Optional[str] = None
    CLAUDE_BASE_URL: Optional[str] = None

    GEMINI_API_KEY: Optional[str] = None
    GEMINI_MODEL: Optional[str] = None
    GEMINI_BASE_URL: Optional[str] = None
    
    DEEPSEEK_REASONER_API_KEY: Optional[str] = None
    DEEPSEEK_REASONER_MODEL: Optional[str] = None
    DEEPSEEK_REASONER_BASE_URL: Optional[str] = None

    # API URLs
    ZEO_API_BASE_URL: str
    MACE_API_BASE_URL: str
    CONVERTER_API_BASE_URL: str
    XTB_API_BASE_URL: str

    # Database Configuration
    DATABASE_URL: str

    # Celery Configuration
    CELERY_BROKER_URL: str
    CELERY_RESULT_BACKEND: str

    # File Storage Path
    FILE_STORAGE_PATH: str

settings = Settings()

