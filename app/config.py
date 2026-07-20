import os
from typing import Optional
from pydantic import computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    # General configuration
    MOCK_MODE: bool = True
    API_BASE_URL: str = "http://localhost:8000"
    API_KEY: str = "default-dev-key"
    ALLOWED_ORIGINS: str = "http://localhost,http://localhost:8000,http://localhost:3000,http://127.0.0.1:8000"

    @property
    def allowed_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.ALLOWED_ORIGINS.split(",") if origin.strip()]

    # Redis Configuration
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_DB: int = 0
    REDIS_PASSWORD: Optional[str] = None
    SESSION_TTL: int = 7200  # 2 hours in seconds

    # Proxmox VE Configuration
    PROXMOX_HOST: str = "192.168.1.100"
    PROXMOX_PORT: int = 8006
    PROXMOX_USER: str = "root@pam"
    PROXMOX_PASSWORD: Optional[str] = None
    PROXMOX_TOKEN_NAME: Optional[str] = None
    PROXMOX_TOKEN_VALUE: Optional[str] = None
    PROXMOX_VERIFY_SSL: bool = True

    # IPED Instance Config
    IPED_API_PORT: int = 80

    @computed_field
    @property
    def REDIS_URL(self) -> str:
        if self.REDIS_PASSWORD:
            from urllib.parse import quote_plus
            escaped_pass = quote_plus(self.REDIS_PASSWORD)
            return f"redis://:{escaped_pass}@{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"
        return f"redis://{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"

    @computed_field
    @property
    def CELERY_BROKER_URL(self) -> str:
        return self.REDIS_URL

    @computed_field
    @property
    def CELERY_RESULT_BACKEND(self) -> str:
        return self.REDIS_URL


# Global settings instance
settings = Settings()
