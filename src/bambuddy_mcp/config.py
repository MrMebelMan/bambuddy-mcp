"""Configuration management via environment variables."""

import os
from dataclasses import dataclass


@dataclass
class Config:
    """Configuration for the Bambuddy MCP server."""

    base_url: str
    api_key: str
    direct_mode: bool

    @classmethod
    def from_env(cls) -> "Config":
        """Load configuration from environment variables."""
        return cls(
            base_url=os.environ.get("BAMBUDDY_URL", "http://localhost:8000"),
            api_key=os.environ.get("BAMBUDDY_API_KEY", ""),
            direct_mode=os.environ.get("BAMBUDDY_DIRECT_MODE", "").lower()
            in ("1", "true", "yes"),
        )
