from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_name: str = "College Club Platform"
    secret_key: str = "change-me-in-production-college-club-platform-secret"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 480
    database_url: str = "sqlite:///./college_club.db"
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    class Config:
        env_file = ".env"


settings = Settings()
