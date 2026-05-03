"""Configuration for the external Multi-LLM Hub adapter."""

from __future__ import annotations

import os
from dataclasses import dataclass

LLM_HUB_URL_ENV = "LLM_HUB_URL"
DEFAULT_LLM_HUB_URL = "http://127.0.0.1:9600"


@dataclass(frozen=True)
class MultiLlmHubConfig:
    """Resolved external Hub connection settings."""

    base_url: str = DEFAULT_LLM_HUB_URL


def load_multi_llm_hub_config() -> MultiLlmHubConfig:
    """Resolve Hub settings from the environment."""

    return MultiLlmHubConfig(
        base_url=os.environ.get(LLM_HUB_URL_ENV, DEFAULT_LLM_HUB_URL).rstrip("/"),
    )


__all__ = [
    "DEFAULT_LLM_HUB_URL",
    "LLM_HUB_URL_ENV",
    "MultiLlmHubConfig",
    "load_multi_llm_hub_config",
]
