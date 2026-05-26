"""Application settings via pydantic-settings.

Every environment variable is explicitly declared so there is no
ambiguity.  Field names are **lowercase** Python names (``settings.host``),
env var names are **uppercase** ``FPE_*`` (``FPE_HOST``).

.env file example::

    FPE_HOST=10.220.21.237
    FPE_NAMESPACE=ns1
    FPE_SSH_USER=admin
"""

from __future__ import annotations

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """FPE application settings, loaded from environment variables or .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── Execution context ──────────────────────────────────────────────
    host: str | None = Field(
        default=None,
        validation_alias=AliasChoices("FPE_HOST", "FPE_TARGET_HOST"),
    )
    namespace: str | None = Field(default=None, validation_alias="FPE_NAMESPACE")
    vrf: str | None = Field(default=None, validation_alias="FPE_VRF")
    ip_version: int = Field(default=4, validation_alias="FPE_IP_VERSION")
    ingress_if: str | None = Field(default=None, validation_alias="FPE_INGRESS_IF")

    # ── SSH ────────────────────────────────────────────────────────────
    target_host: str | None = Field(default=None, validation_alias="FPE_TARGET_HOST")
    target_hosts: str | None = Field(default=None, validation_alias="FPE_TARGET_HOSTS")
    ssh_user: str = Field(default="root", validation_alias="FPE_SSH_USER")
    ssh_port: int = Field(default=22, validation_alias="FPE_SSH_PORT")
    ssh_key_path: str | None = Field(default=None, validation_alias="FPE_SSH_KEY_PATH")
    ssh_connect_timeout: int = Field(default=10, validation_alias="FPE_SSH_CONNECT_TIMEOUT")

    # ── LLM / model ────────────────────────────────────────────────────
    model_base_url: str = Field(
        default="https://api.example.com/v1",
        validation_alias="FPE_MODEL_BASE_URL",
    )
    model_api_key: str = Field(default="", validation_alias="FPE_MODEL_API_KEY")
    model_name: str = Field(default="claude-sonnet-4-6", validation_alias="FPE_MODEL_NAME")
    model_timeout: int = Field(default=30, validation_alias="FPE_MODEL_TIMEOUT")

    # ── Behaviour ──────────────────────────────────────────────────────
    enable_ovs: bool = Field(default=True, validation_alias="FPE_ENABLE_OVS")
    default_max_hops: int = Field(default=16, validation_alias="FPE_DEFAULT_MAX_HOPS")
    log_level: str = Field(default="INFO", validation_alias="FPE_LOG_LEVEL")


settings = Settings()
