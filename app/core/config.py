from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = Field(default="chat-oracle", alias="APP_NAME")
    app_env: str = Field(default="production", alias="APP_ENV")
    app_host: str = Field(default="0.0.0.0", alias="APP_HOST")
    app_port: int = Field(default=8000, alias="APP_PORT")
    app_bind_port: int = Field(default=18000, alias="APP_BIND_PORT")
    api_v1_prefix: str = Field(default="/v1", alias="API_V1_PREFIX")
    cors_origins: list[str] = Field(default=["*"], alias="CORS_ORIGINS")

    postgres_host: str = Field(default="localhost", alias="POSTGRES_HOST")
    postgres_port: int = Field(default=5432, alias="POSTGRES_PORT")
    postgres_db: str = Field(default="chat_oracle", alias="POSTGRES_DB")
    postgres_user: str = Field(default="chat_oracle", alias="POSTGRES_USER")
    postgres_password: str = Field(default="change-me", alias="POSTGRES_PASSWORD")

    redis_host: str = Field(default="localhost", alias="REDIS_HOST")
    redis_port: int = Field(default=6379, alias="REDIS_PORT")
    redis_db: int = Field(default=0, alias="REDIS_DB")
    redis_password: str | None = Field(default=None, alias="REDIS_PASSWORD")

    jwt_secret: str = Field(default="change-me", alias="JWT_SECRET")
    jwt_algorithm: str = Field(default="HS256", alias="JWT_ALGORITHM")
    jwt_access_expire_minutes: int = Field(default=30, alias="JWT_ACCESS_EXPIRE_MINUTES")
    jwt_refresh_expire_days: int = Field(default=14, alias="JWT_REFRESH_EXPIRE_DAYS")

    default_free_plan_code: str = Field(default="free", alias="DEFAULT_FREE_PLAN_CODE")
    project_domain: str = Field(default="chat.202574.xyz", alias="PROJECT_DOMAIN")
    public_base_url: str | None = Field(default=None, alias="PUBLIC_BASE_URL")
    llm_openai_compat_base_url: str = Field(default="https://sd3.202574.xyz/v1", alias="LLM_OPENAI_COMPAT_BASE_URL")
    llm_openai_compat_api_key: str = Field(default="", alias="LLM_OPENAI_COMPAT_API_KEY")
    llm_default_node_code: str = Field(default="gemma-e2b-local", alias="LLM_DEFAULT_NODE_CODE")
    llm_default_provider_code: str = Field(default="gemma", alias="LLM_DEFAULT_PROVIDER_CODE")
    llm_default_model_name: str = Field(
        default="gemma-4-e2b-q6_k_p",
        alias="LLM_DEFAULT_MODEL_NAME",
    )
    llm_default_model: str = Field(
        default="gemma-4-e2b-q6_k_p",
        alias="LLM_DEFAULT_MODEL",
    )
    llm_fallback_node_code: str = Field(default="gemma-primary", alias="LLM_FALLBACK_NODE_CODE")
    llm_fallback_provider_code: str = Field(default="gemma", alias="LLM_FALLBACK_PROVIDER_CODE")
    llm_fallback_model_name: str = Field(
        default="gemma-4-31B-Mystery-Fine-Tune-HERETIC-UNCENSORED-INSTRUCT-Q4_K_S.gguf",
        alias="LLM_FALLBACK_MODEL_NAME",
    )
    llm_fallback_model: str = Field(
        default="gemma/gemma-4-31B-Mystery-Fine-Tune-HERETIC-UNCENSORED-INSTRUCT-Q4_K_S.gguf",
        alias="LLM_FALLBACK_MODEL",
    )
    llm_local_base_url: str = Field(default="http://host.docker.internal:11435/v1", alias="LLM_LOCAL_BASE_URL")
    llm_local_api_key: str = Field(default="dummy", alias="LLM_LOCAL_API_KEY")
    llm_request_timeout_seconds: int = Field(default=180, alias="LLM_REQUEST_TIMEOUT_SECONDS")
    phone_api_base_url: str = Field(default="https://ca2.202574.xyz/api", alias="PHONE_API_BASE_URL")
    phone_api_country: str = Field(default="FI", alias="PHONE_API_COUNTRY")
    phone_api_timeout_seconds: int = Field(default=180, alias="PHONE_API_TIMEOUT_SECONDS")
    phone_api_poll_interval_seconds: int = Field(default=30, alias="PHONE_API_POLL_INTERVAL_SECONDS")
    phone_current_number_ttl_seconds: int = Field(default=604800, alias="PHONE_CURRENT_NUMBER_TTL_SECONDS")
    telegram_bridge_api_id: int | None = Field(default=None, alias="TELEGRAM_BRIDGE_API_ID")
    telegram_bridge_api_hash: str | None = Field(default=None, alias="TELEGRAM_BRIDGE_API_HASH")
    telegram_bridge_session_string: str | None = Field(default=None, alias="TELEGRAM_BRIDGE_SESSION_STRING")
    telegram_bridge_session_file: str = Field(
        default=".telegram-oracle.session",
        alias="TELEGRAM_BRIDGE_SESSION_FILE",
    )
    telegram_bridge_target_bot_username: str | None = Field(default=None, alias="TELEGRAM_BRIDGE_TARGET_BOT_USERNAME")
    telegram_bridge_required_peers: str = Field(default="", alias="TELEGRAM_BRIDGE_REQUIRED_PEERS")
    telegram_bridge_bootstrap_start_message: str = Field(
        default="/start",
        alias="TELEGRAM_BRIDGE_BOOTSTRAP_START_MESSAGE",
    )
    telegram_bridge_request_timeout_seconds: int = Field(
        default=180,
        alias="TELEGRAM_BRIDGE_REQUEST_TIMEOUT_SECONDS",
    )
    telegram_audit_node_code: str = Field(default="telegram-audit-gemini", alias="TELEGRAM_AUDIT_NODE_CODE")
    telegram_audit_provider_code: str = Field(default="google-gemini", alias="TELEGRAM_AUDIT_PROVIDER_CODE")
    telegram_audit_gemini_base_url: str = Field(
        default="https://generativelanguage.googleapis.com/v1beta/openai",
        alias="TELEGRAM_AUDIT_GEMINI_BASE_URL",
    )
    telegram_audit_gemini_api_key: str | None = Field(default=None, alias="TELEGRAM_AUDIT_GEMINI_API_KEY")
    telegram_audit_gemini_model: str = Field(default="gemini-2.5-flash", alias="TELEGRAM_AUDIT_GEMINI_MODEL")
    telegram_audit_gemini_fallback_models_raw: str = Field(
        default="gemini-2.5-flash,gemini-2.5-pro,gemini-pro-latest",
        alias="TELEGRAM_AUDIT_GEMINI_FALLBACK_MODELS",
    )
    telegram_bridge_parse_timeout_seconds: int = Field(
        default=120,
        alias="TELEGRAM_BRIDGE_PARSE_TIMEOUT_SECONDS",
    )
    telegram_bridge_inline_text_max_chars: int = Field(
        default=12000,
        alias="TELEGRAM_BRIDGE_INLINE_TEXT_MAX_CHARS",
    )
    telegram_bridge_download_ttl_seconds: int = Field(
        default=86400,
        alias="TELEGRAM_BRIDGE_DOWNLOAD_TTL_SECONDS",
    )
    web_search_tavily_api_key: str | None = Field(default=None, alias="WEB_SEARCH_TAVILY_API_KEY")
    web_search_tavily_base_url: str = Field(default="https://api.tavily.com", alias="WEB_SEARCH_TAVILY_BASE_URL")
    web_search_tavily_extract_depth: str = Field(default="advanced", alias="WEB_SEARCH_TAVILY_EXTRACT_DEPTH")
    web_search_searxng_base_url: str | None = Field(default=None, alias="WEB_SEARCH_SEARXNG_BASE_URL")
    web_search_searxng_language: str = Field(default="zh-CN", alias="WEB_SEARCH_SEARXNG_LANGUAGE")
    web_search_llm_node_code: str | None = Field(default=None, alias="WEB_SEARCH_LLM_NODE_CODE")
    web_search_provider_preference_raw: str = Field(
        default="tavily,searxng",
        alias="WEB_SEARCH_PROVIDER_PREFERENCE",
    )
    web_search_default_search_depth: str = Field(default="advanced", alias="WEB_SEARCH_DEFAULT_SEARCH_DEPTH")
    web_search_timeout_seconds: int = Field(default=60, alias="WEB_SEARCH_TIMEOUT_SECONDS")
    web_search_extract_timeout_seconds: int = Field(default=90, alias="WEB_SEARCH_EXTRACT_TIMEOUT_SECONDS")
    web_search_max_results: int = Field(default=8, alias="WEB_SEARCH_MAX_RESULTS")
    web_search_max_extract_urls: int = Field(default=5, alias="WEB_SEARCH_MAX_EXTRACT_URLS")
    web_search_max_queries: int = Field(default=3, alias="WEB_SEARCH_MAX_QUERIES")
    web_search_max_context_chars: int = Field(default=12000, alias="WEB_SEARCH_MAX_CONTEXT_CHARS")
    web_search_max_evidence_chunks: int = Field(default=6, alias="WEB_SEARCH_MAX_EVIDENCE_CHUNKS")
    web_search_max_document_chars: int = Field(default=20000, alias="WEB_SEARCH_MAX_DOCUMENT_CHARS")
    web_search_min_result_score: float = Field(default=1.0, alias="WEB_SEARCH_MIN_RESULT_SCORE")
    web_search_min_evidence_score: float = Field(default=2.0, alias="WEB_SEARCH_MIN_EVIDENCE_SCORE")
    web_search_blocked_domains_raw: str = Field(
        default="codecanyon.net,mcpmarket.com,mindstudio.ai",
        alias="WEB_SEARCH_BLOCKED_DOMAINS",
    )
    web_search_user_agent: str = Field(
        default="chat-oracle-web-search/1.0",
        alias="WEB_SEARCH_USER_AGENT",
    )
    qiandu_tavily_api_key: str | None = Field(default=None, alias="QIANDU_TAVILY_API_KEY")
    qiandu_tavily_base_url: str = Field(default="https://api.tavily.com", alias="QIANDU_TAVILY_BASE_URL")
    qiandu_exa_api_key: str | None = Field(default=None, alias="QIANDU_EXA_API_KEY")
    exa_api_key: str | None = Field(default=None, alias="EXA_API_KEY")
    qiandu_exa_base_url: str = Field(default="https://api.exa.ai", alias="QIANDU_EXA_BASE_URL")
    qiandu_searxng_base_url: str | None = Field(default=None, alias="QIANDU_SEARXNG_BASE_URL")
    qiandu_searxng_language: str = Field(default="zh-CN", alias="QIANDU_SEARXNG_LANGUAGE")
    qiandu_searxng_engines_raw: str = Field(default="baidu,sogou", alias="QIANDU_SEARXNG_ENGINES")
    qiandu_llm_node_code: str | None = Field(default=None, alias="QIANDU_LLM_NODE_CODE")
    qiandu_provider_preference_raw: str = Field(
        default="snoop,wechat_crawler,tavily,exa,searxng",
        alias="QIANDU_PROVIDER_PREFERENCE",
    )
    qiandu_timeout_seconds: int = Field(default=90, alias="QIANDU_TIMEOUT_SECONDS")
    qiandu_extract_timeout_seconds: int = Field(default=120, alias="QIANDU_EXTRACT_TIMEOUT_SECONDS")
    qiandu_max_results: int = Field(default=10, alias="QIANDU_MAX_RESULTS")
    qiandu_max_extract_urls: int = Field(default=5, alias="QIANDU_MAX_EXTRACT_URLS")
    qiandu_max_queries: int = Field(default=4, alias="QIANDU_MAX_QUERIES")
    qiandu_max_search_tasks: int = Field(default=8, alias="QIANDU_MAX_SEARCH_TASKS")
    qiandu_max_context_chars: int = Field(default=14000, alias="QIANDU_MAX_CONTEXT_CHARS")
    qiandu_max_evidence_chunks: int = Field(default=8, alias="QIANDU_MAX_EVIDENCE_CHUNKS")
    qiandu_max_document_chars: int = Field(default=24000, alias="QIANDU_MAX_DOCUMENT_CHARS")
    qiandu_report_inline_max_chars: int = Field(default=6000, alias="QIANDU_REPORT_INLINE_MAX_CHARS")
    qiandu_snoop_command: str | None = Field(default=None, alias="QIANDU_SNOOP_COMMAND")
    qiandu_wechat_crawler_command: str | None = Field(default=None, alias="QIANDU_WECHAT_CRAWLER_COMMAND")
    qiandu_crawl4ai_enabled: bool = Field(default=True, alias="QIANDU_CRAWL4AI_ENABLED")
    qiandu_crawl4ai_headless: bool = Field(default=True, alias="QIANDU_CRAWL4AI_HEADLESS")
    qiandu_crawl4ai_cookies_json: str | None = Field(default=None, alias="QIANDU_CRAWL4AI_COOKIES_JSON")
    qiandu_crawl4ai_headers_json: str | None = Field(default=None, alias="QIANDU_CRAWL4AI_HEADERS_JSON")
    qiandu_crawl4ai_profile_dir: str | None = Field(default=None, alias="QIANDU_CRAWL4AI_PROFILE_DIR")
    bepusdt_base_url: str | None = Field(default=None, alias="BEPUSDT_BASE_URL")
    bepusdt_api_token: str | None = Field(default=None, alias="BEPUSDT_API_TOKEN")
    bepusdt_currencies: str = Field(default="USDT", alias="BEPUSDT_CURRENCIES")
    bepusdt_timeout_seconds: int = Field(default=1200, alias="BEPUSDT_TIMEOUT_SECONDS")
    bepusdt_request_timeout_seconds: int = Field(default=30, alias="BEPUSDT_REQUEST_TIMEOUT_SECONDS")
    bepusdt_trade_type: str = Field(default="usdt.trc20", alias="BEPUSDT_TRADE_TYPE")
    bepusdt_redirect_path: str = Field(default="/chat?billing=success", alias="BEPUSDT_REDIRECT_PATH")
    admin_bootstrap_email: str | None = Field(default=None, alias="ADMIN_BOOTSTRAP_EMAIL")
    admin_bootstrap_password: str | None = Field(default=None, alias="ADMIN_BOOTSTRAP_PASSWORD")

    @property
    def database_url_async(self) -> str:
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def database_url_sync(self) -> str:
        return (
            f"postgresql://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def redis_url(self) -> str:
        auth = f":{self.redis_password}@" if self.redis_password else ""
        return f"redis://{auth}{self.redis_host}:{self.redis_port}/{self.redis_db}"

    @property
    def resolved_public_base_url(self) -> str:
        if self.public_base_url:
            return self.public_base_url.rstrip("/")
        return f"https://{self.project_domain}".rstrip("/")

    @property
    def telegram_bridge_enabled(self) -> bool:
        return bool(
            self.telegram_bridge_api_id
            and self.telegram_bridge_api_hash
            and self.telegram_bridge_target_bot_username
        )

    @property
    def telegram_audit_gemini_enabled(self) -> bool:
        return bool((self.telegram_audit_gemini_api_key or "").strip())

    @property
    def telegram_audit_gemini_fallback_models(self) -> list[str]:
        return [
            item.strip()
            for item in self.telegram_audit_gemini_fallback_models_raw.split(",")
            if item.strip()
        ]

    @property
    def web_search_provider_preference(self) -> list[str]:
        return [
            item.strip()
            for item in self.web_search_provider_preference_raw.split(",")
            if item.strip()
        ]

    @property
    def web_search_enabled(self) -> bool:
        return bool(self.web_search_tavily_api_key or self.web_search_searxng_base_url)

    @property
    def resolved_web_search_llm_node_code(self) -> str:
        return (self.web_search_llm_node_code or self.llm_fallback_node_code).strip()

    @property
    def web_search_blocked_domains(self) -> list[str]:
        return [
            item.strip().lower()
            for item in self.web_search_blocked_domains_raw.split(",")
            if item.strip()
        ]

    @property
    def qiandu_provider_preference(self) -> list[str]:
        return [
            item.strip()
            for item in self.qiandu_provider_preference_raw.split(",")
            if item.strip()
        ]

    @property
    def qiandu_searxng_engines(self) -> list[str]:
        return [
            item.strip()
            for item in self.qiandu_searxng_engines_raw.split(",")
            if item.strip()
        ]

    @property
    def qiandu_enabled(self) -> bool:
        return bool(
            self.qiandu_tavily_api_key
            or self.web_search_tavily_api_key
            or self.resolved_qiandu_exa_api_key
            or self.qiandu_searxng_base_url
            or self.web_search_searxng_base_url
            or self.qiandu_snoop_command
            or self.qiandu_wechat_crawler_command
            or "snoop" in self.qiandu_provider_preference
            or "wechat_crawler" in self.qiandu_provider_preference
        )

    @property
    def resolved_qiandu_llm_node_code(self) -> str:
        return (self.qiandu_llm_node_code or self.resolved_web_search_llm_node_code).strip()

    @property
    def resolved_qiandu_exa_api_key(self) -> str | None:
        return (self.qiandu_exa_api_key or self.exa_api_key or "").strip() or None


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
