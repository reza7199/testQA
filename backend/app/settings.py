from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="UIQA_", extra="ignore")

    DB_URL: str = "sqlite:///./uiqa.sqlite"
    REDIS_URL: str = "redis://localhost:6379/0"
    ARTIFACTS_DIR: str = "./artifacts"

    # For GitHub Issues / PR creation (optional)
    GITHUB_TOKEN: str | None = None

settings = Settings()
