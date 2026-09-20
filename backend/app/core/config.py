import os
from typing import List
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    PROJECT_NAME: str = "Document-to-Action Pipeline API"
    VERSION: str = "0.1.0"
    ENVIRONMENT: str = "development"
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    CORS_ORIGINS: str = "http://localhost:5173,http://127.0.0.1:5173"
    SUPABASE_URL: str = ""
    SUPABASE_KEY: str = ""
    TESSERACT_CMD: str = ""
    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-2.5-flash"
    CLASSIFICATION_CONFIDENCE_THRESHOLD: float = 0.70
    INVOICE_ROUNDING_TOLERANCE: float = 0.05
    VISION_FALLBACK_CONFIDENCE_THRESHOLD: float = 0.70
    VISION_CROP_PADDING: int = 25
    VISION_FALLBACK_MAX_ATTEMPTS: int = 1

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    @property
    def cors_origin_list(self) -> List[str]:
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()]


settings = Settings()
