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
    default_tenant_id: str = "default"
    default_platform: str = "douyin"
    storage_root: Path = BASE_DIR / "storage"
    douyin_tenants_dir: Path = BASE_DIR / "storage" / "douyin" / "tenants"
    douyin_storage_state_path: Path = BASE_DIR / "storage" / "douyin" / "storage_state.json"
    douyin_profile_dir: Path = BASE_DIR / "storage" / "douyin" / "profile"
    douyin_vnc_url: str = "http://localhost:6080/vnc.html?autoconnect=true&resize=scale"
    douyin_headless: bool = True

    xhs_home_url: str = "https://www.xiaohongshu.com"
    xhs_explore_url: str = "https://www.xiaohongshu.com/explore"
    xhs_headless: bool = True
    xhs_vnc_url: str = "http://localhost:6080/vnc.html?autoconnect=true&resize=scale"

    huoshan_home_url: str = "https://www.huoshan.com"
    huoshan_hot_url: str = "https://www.douyin.com/hot"
    huoshan_headless: bool = True
    huoshan_vnc_url: str = "http://localhost:6080/vnc.html?autoconnect=true&resize=scale"
    huoshan_seed_user_ids: Optional[str] = None
    huoshan_hot_mode: str = "seed_then_fallback"

    kuaishou_home_url: str = "https://www.kuaishou.com"
    kuaishou_headless: bool = True
    kuaishou_vnc_url: str = "http://localhost:6080/vnc.html?autoconnect=true&resize=scale"

    antibot_enabled: bool = True
    antibot_stealth_enabled: bool = True
    antibot_require_login: bool = True
    antibot_delay_min_ms: float = 2000
    antibot_delay_max_ms: float = 6000
    antibot_user_agent: Optional[str] = None
    antibot_viewport_width: int = 1440
    antibot_viewport_height: int = 1200
    antibot_locale: str = "zh-CN"

    crawl_hour: int = 8
    crawl_minute: int = 0

    openai_api_key: Optional[str] = None
    openai_base_url: str = "https://api.openai.com/v1"
    openai_model: str = "gpt-4.1-mini"

    deepseek_api_key: Optional[str] = None
    deepseek_base_url: str = "https://api.deepseek.com/v1"
    deepseek_model: str = "deepseek-chat"

    agent_max_steps: int = 100
    agent_default_provider: str = "openai"
    agent_headless: bool = True
    agent_vision_enabled: bool = True
    agent_vision_model: Optional[str] = None
    agent_max_history_messages: int = 40
    agent_default_run_mode: str = "auto"
    agent_checkpoints_enabled: bool = True
    agent_checkpoint_max_count: int = 20
    agent_subagent_max_steps: int = 100
    agent_stream_enabled: bool = True
    agent_compress_enabled: bool = True
    agent_compress_threshold_messages: int = 30
    agent_compress_keep_recent: int = 12
    agent_dream_enabled: bool = True
    agent_dream_auto: bool = True
    agent_dream_use_llm: bool = False
    agent_dream_inject_max: int = 5

    skillhub_registry: str = "https://skill.xfyun.cn"
    skillhub_token: Optional[str] = None
    skillhub_auto_install_enabled: bool = True
    skillhub_script_timeout_seconds: int = 120

    report_output_dir: Path = BASE_DIR / "reports"

    tenant_auth_enabled: bool = False
    tenant_auth_pepper: str = "change-me-in-production"
    user_auth_pepper: str = "change-me-in-production"
    jwt_secret: str = "change-me-jwt-secret-in-production"
    jwt_expire_minutes: int = 60 * 24 * 7
    huoke_bridge_secret: Optional[str] = None
    admin_api_secret: Optional[str] = None
    tenant_bootstrap_api_keys: Optional[str] = None
    storage_state_encryption_key: Optional[str] = None


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.storage_root.mkdir(parents=True, exist_ok=True)
    settings.douyin_tenants_dir.mkdir(parents=True, exist_ok=True)
    settings.douyin_storage_state_path.parent.mkdir(parents=True, exist_ok=True)
    settings.douyin_profile_dir.mkdir(parents=True, exist_ok=True)
    settings.report_output_dir.mkdir(parents=True, exist_ok=True)
    return settings
