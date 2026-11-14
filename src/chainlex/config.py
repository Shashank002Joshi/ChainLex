"""Validated environment configuration shared by the three processes."""

from typing import Literal, Self

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from chainlex.services.embeddings import EMBEDDING_MODEL


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CHAINLEX_", env_file=".env", extra="ignore")

    mongodb_uri: SecretStr | None = None
    database: str = Field(default="chainlex_dev", pattern=r"^[A-Za-z0-9_-]{1,63}$")
    database_timeout_ms: int = Field(default=2000, ge=100, le=30000)
    demo_tenant_id: str = Field(default="bank_a", min_length=1, max_length=128)
    analyst_token: SecretStr = SecretStr("")
    officer_token: SecretStr = SecretStr("")
    simulator_token: SecretStr = SecretStr("")
    simulator_url: str = "http://127.0.0.1:8001"
    simulator_confirmation_seconds: float = Field(default=2, ge=0, le=300)
    voyage_api_key: SecretStr = SecretStr("")
    embedding_model: Literal["voyage-finance-2"] = EMBEDDING_MODEL
    rerank_model: str = "rerank-2.5"
    llm_api_key: SecretStr = SecretStr("")
    llm_model: str = ""
    lease_seconds: int = Field(default=10, ge=2)
    heartbeat_seconds: float = Field(default=3, gt=0)
    poll_seconds: float = Field(default=1, gt=0)

    @model_validator(mode="after")
    def validate_runtime(self) -> Self:
        if self.heartbeat_seconds >= self.lease_seconds:
            raise ValueError("heartbeat_seconds must be shorter than lease_seconds")
        tokens = [
            token.get_secret_value()
            for token in (self.analyst_token, self.officer_token, self.simulator_token)
            if token.get_secret_value()
        ]
        if len(set(tokens)) != len(tokens):
            raise ValueError("Configured role and simulator tokens must be distinct")
        if any(token != token.strip() for token in tokens):
            raise ValueError("Tokens must not contain surrounding whitespace")
        return self
