from functools import lru_cache
from pathlib import Path
from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


BASE_DIR = Path(__file__).resolve().parents[2]
ROOT_DIR = BASE_DIR.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(BASE_DIR / ".env", ROOT_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Douyin Hot Monitor"
    debug: bool = False
    api_prefix: str = "/api"
    timezone: str = "Asia/Shanghai"

    database_url: str = Field(
        default="mysql+pymysql://douyin:douyin@mysql:3306/douyin_hot?charset=utf8mb4"
    )
    sqlite_test_url: str = "sqlite+pysqlite:///:memory:"

    frontend_origin: str = "http://localhost:5173"

    douyin_hot_url: str = "https://www.douyin.com/hot"
    douyin_storage_state_path: Path = BASE_DIR / "storage" / "douyin" / "storage_state.json"
    douyin_profile_dir: Path = BASE_DIR / "storage" / "douyin" / "profile"
    douyin_vnc_url: str = "http://localhost:6080/vnc.html?autoconnect=true&resize=scale"
    douyin_headless: bool = True
    crawl_hour: int = 8
    crawl_minute: int = 0

    openai_api_key: Optional[str] = None
    openai_base_url: str = "https://api.openai.com/v1"
    openai_model: str = "gpt-4.1-mini"

    deepseek_api_key: Optional[str] = None
    deepseek_base_url: str = "https://api.deepseek.com/v1"
    deepseek_model: str = "deepseek-chat"

    report_output_dir: Path = BASE_DIR / "reports"


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.douyin_storage_state_path.parent.mkdir(parents=True, exist_ok=True)
    settings.douyin_profile_dir.mkdir(parents=True, exist_ok=True)
    settings.report_output_dir.mkdir(parents=True, exist_ok=True)
    return settings
