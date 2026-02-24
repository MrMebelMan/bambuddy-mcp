"""Configuration management via environment variables."""

import os
from dataclasses import dataclass


@dataclass
class Config:
    """Configuration for the Bambuddy MCP server."""

    base_url: str
    api_key: str
    direct_mode: bool
    censor_access_code: bool
    censor_serial: bool
    censor_model_filename: bool

    @classmethod
    def from_env(cls) -> "Config":
        """Load configuration from environment variables."""

        def _bool_env(name: str, default: str) -> bool:
            return os.environ.get(name, default).lower() not in ("0", "false", "no")

        return cls(
            base_url=os.environ.get("BAMBUDDY_URL", "http://localhost:8000"),
            api_key=os.environ.get("BAMBUDDY_API_KEY", ""),
            direct_mode=os.environ.get("BAMBUDDY_DIRECT_MODE", "").lower()
            in ("1", "true", "yes"),
            censor_access_code=_bool_env("BAMBUDDY_CENSOR_ACCESS_CODE", "true"),
            censor_serial=_bool_env("BAMBUDDY_CENSOR_SERIAL", "true"),
            censor_model_filename=_bool_env("BAMBUDDY_CENSOR_MODEL_FILENAME", "false"),
        )
