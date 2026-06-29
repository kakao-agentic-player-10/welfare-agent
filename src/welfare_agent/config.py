from dataclasses import dataclass
import os

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    data_go_kr_service_key: str
    youth_policy_api_key: str
    openai_api_key: str
    openai_embedding_model: str
    openai_embedding_dimensions: int
    sqlite_path: str
    public_service_api_url: str
    youth_policy_api_url: str
    kakao_rest_api_key: str
    sync_enabled: bool
    sync_on_startup: bool
    sync_daily: bool
    sync_hour: int
    sync_minute: int
    sync_timezone: str
    sync_page_size: int
    sync_max_pages: int
    sync_batch_size: int
    sync_mode: str
    support_conditions_enrichment_enabled: bool
    support_conditions_enrichment_request_limit: int
    support_conditions_enrichment_limit: int
    support_conditions_enrichment_batch_size: int
    host: str
    port: int
    path: str


# .env와 환경변수를 읽어 서버/API 설정 객체로 묶는다.
def load_settings() -> Settings:
    load_dotenv()
    data_go_kr_service_key = os.getenv("DATA_GO_KR_SERVICE_KEY", "").strip()
    legacy_public_service_key = os.getenv("PUBLIC_SERVICE_API_KEY", "").strip()
    support_conditions_request_limit = int(
        os.getenv("WELFARE_SUPPORT_CONDITIONS_REQUEST_LIMIT", "8000")
    )
    return Settings(
        data_go_kr_service_key=data_go_kr_service_key or legacy_public_service_key,
        youth_policy_api_key=os.getenv("YOUTH_POLICY_API_KEY", "").strip(),
        openai_api_key=os.getenv("OPENAI_API_KEY", "").strip(),
        openai_embedding_model=os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small").strip(),
        openai_embedding_dimensions=int(os.getenv("OPENAI_EMBEDDING_DIMENSIONS", "1536")),
        sqlite_path=os.getenv("SQLITE_PATH", "./data/welfare-agent.db").strip(),
        public_service_api_url=os.getenv("PUBLIC_SERVICE_API_URL", "").strip(),
        youth_policy_api_url=os.getenv("YOUTH_POLICY_API_URL", "").strip(),
        kakao_rest_api_key=os.getenv("KAKAO_REST_API_KEY", "").strip(),
        sync_enabled=env_bool("WELFARE_SYNC_ENABLED", True),
        sync_on_startup=env_bool("WELFARE_SYNC_ON_STARTUP", True),
        sync_daily=env_bool("WELFARE_SYNC_DAILY", True),
        sync_hour=int(os.getenv("WELFARE_SYNC_HOUR", "3")),
        sync_minute=int(os.getenv("WELFARE_SYNC_MINUTE", "30")),
        sync_timezone=os.getenv("WELFARE_SYNC_TIMEZONE", "Asia/Seoul").strip(),
        sync_page_size=int(os.getenv("WELFARE_SYNC_PAGE_SIZE", "100")),
        sync_max_pages=int(os.getenv("WELFARE_SYNC_MAX_PAGES", "200")),
        sync_batch_size=int(os.getenv("WELFARE_SYNC_BATCH_SIZE", "64")),
        sync_mode=os.getenv("WELFARE_SYNC_MODE", "auto").strip(),
        support_conditions_enrichment_enabled=env_bool(
            "WELFARE_SUPPORT_CONDITIONS_ENABLED", True
        ),
        support_conditions_enrichment_request_limit=support_conditions_request_limit,
        support_conditions_enrichment_limit=int(
            os.getenv("WELFARE_SUPPORT_CONDITIONS_LIMIT", str(support_conditions_request_limit))
        ),
        support_conditions_enrichment_batch_size=int(
            os.getenv("WELFARE_SUPPORT_CONDITIONS_BATCH_SIZE", "100")
        ),
        host=os.getenv("HOST", "0.0.0.0").strip(),
        port=int(os.getenv("PORT", "8000")),
        path=os.getenv("MCP_PATH", "/mcp").strip(),
    )


def env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}
