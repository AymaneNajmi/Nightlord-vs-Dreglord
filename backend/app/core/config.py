from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parents[2]  # backend/
ENV_PATH = BASE_DIR / ".env"

class Settings(BaseSettings):
    DATABASE_URL: str
    JWT_SECRET: str = "change_me_secret"
    JWT_ALG: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MIN: int = 60
    AUTH_COOKIE_NAME: str = "aidocgen_access_token"
    AUTH_COOKIE_SECURE: bool = True
    AUTH_COOKIE_SAMESITE: str = "lax"
    AUTH_COOKIE_DOMAIN: str | None = None
    AUTH_COOKIE_PATH: str = "/"
    ADMIN_EMAIL: str = "admin@example.com"
    ADMIN_PASSWORD: str = "admin123"
    USER_EMAIL: str = "engineer@test.com"
    USER_PASSWORD: str = "engineer123"

    model_config = SettingsConfigDict(env_file=str(ENV_PATH), extra="ignore")

settings = Settings()
