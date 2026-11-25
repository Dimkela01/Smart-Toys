"""Application settings. Secrets come from the environment only (docs/CLAUDE.md §2)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

Environment = Literal["demo", "pilot", "eval"]
Profile = Literal["server", "device"]
Language = Literal["sr", "en"]

DEV_JWT_SECRET = "change-me-in-production-at-least-32-characters-long"

#: repo root, so the one .env at the top of the tree is found no matter where a command is
#: started from (host: services/api for pytest; container: /srv/api, where it does not exist
#: because compose passes the variables in the environment instead)
REPO_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(REPO_ROOT / ".env", ".env"),
        extra="ignore",
        case_sensitive=False,
    )

    environment: Environment = "demo"
    public_web_url: str = "http://localhost:3000"
    log_level: str = "INFO"

    # --- database / redis ---
    database_url: str = "postgresql+psycopg://bruno:bruno_dev_password@localhost:5432/bruno"
    test_database_url: str | None = None
    redis_url: str = "redis://localhost:6379/0"
    #: host-visible Redis for pytest (the app itself talks to the container hostname)
    test_redis_url: str | None = None

    # --- auth ---
    jwt_secret: str = DEV_JWT_SECRET
    access_token_minutes: int = 15
    refresh_token_days: int = 30
    #: long enough for a child to pick their picture (F-04, UC-05)
    child_mode_token_minutes: int = 15
    #: one child session on the toy screen; daily limits and hours arrive in M5
    child_session_token_hours: int = 6
    consent_version: str = "2026-11-11"
    #: the refresh cookie needs Secure behind TLS; off for plain-http development
    cookie_secure: bool = False
    #: A refresh token is single use and a replay revokes the device. Two browser tabs
    #: loading at once both present the same cookie, though, and that race is not a leak:
    #: inside this window a replay is answered with a fresh access token and no rotation.
    refresh_reuse_grace_seconds: int = 10
    #: Fernet key for admins.totp_secret_enc; derived from JWT_SECRET when empty (dev only)
    totp_encryption_key: str = ""

    # verification / reset link lifetimes (UC-01, UC-02)
    verify_token_hours: int = 24
    reset_token_hours: int = 1

    # lockouts (UC-02, UC-21)
    login_max_attempts: int = 5
    login_lock_minutes: int = 15
    pin_max_attempts: int = 5
    pin_lock_minutes: int = 5
    auth_rate_limit_per_minute: int = 10
    #: Only true when a reverse proxy we control (Caddy) sets X-Forwarded-For from the
    #: socket. Anything else can forge the header, and NFR-06's per-IP limit would then be
    #: one header away from unlimited. Next.js passes the client's value through unchanged,
    #: so development leaves this off and buckets by the connecting address.
    trust_proxy_headers: bool = False
    #: PIN attempts get a separate, roomier bucket: the 5-attempt lock (UC-21) is the real
    #: control, and sharing the auth bucket would answer 429 before the specified 423
    pin_rate_limit_per_minute: int = 20

    # --- email ---
    smtp_host: str = "localhost"
    smtp_port: int = 1025
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_starttls: bool = False
    smtp_from: str = "bruno@example.com"
    email_print_links: bool = True

    # --- inference (wired up in M2; no model id is hard-coded, F-20) ---
    inference_profile_default: Profile = "server"
    llm_server_url: str = "http://llm:8080"
    stt_server_url: str = "http://stt:8001"
    tts_server_url: str = "http://tts:8002"
    device_tunnel_url: str = ""
    device_tunnel_token: str = ""
    model_registry_path: str = str(REPO_ROOT / "models" / "registry.yaml")

    # --- versioned content (characters, avatars, lessons; NFR-11) ---
    #: mounted read-only into the api container, which does not see the repo root
    content_dir: str = str(REPO_ROOT / "content")
    #: system prompts, versioned in the repository the same way (SAFETY.md §5)
    prompts_dir: str = str(REPO_ROOT / "prompts")

    # --- retention (DATA_MODEL.md §6) ---
    transcript_retention_days: int = 30

    # --- first admin (make seed) ---
    #: must be a full address with a TLD: the login schema validates it as an email
    admin_seed_email: str = "admin@example.com"
    admin_seed_password: str = Field(default="admin_dev_password", repr=False)

    @field_validator("jwt_secret")
    @classmethod
    def _secret_long_enough(cls, value: str) -> str:
        if len(value) < 32:
            raise ValueError("JWT_SECRET must be at least 32 characters")
        return value

    @property
    def is_production_like(self) -> bool:
        return self.environment == "pilot"

    def check_production_safety(self) -> list[str]:
        """Configuration that must never reach a pilot with real families."""
        problems: list[str] = []
        if not self.is_production_like:
            return problems
        if self.jwt_secret == DEV_JWT_SECRET:
            problems.append("JWT_SECRET is still the development default")
        if self.email_print_links:
            problems.append("EMAIL_PRINT_LINKS must be off outside development")
        if self.smtp_host in {"localhost", "mailpit"}:
            problems.append("SMTP_HOST still points at the local mail catcher")
        if not self.cookie_secure:
            problems.append("COOKIE_SECURE must be on behind TLS (NFR-05)")
        if not self.totp_encryption_key:
            problems.append("TOTP_ENCRYPTION_KEY must be set; otherwise rotating JWT_SECRET locks out admins")
        return problems


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
