from __future__ import annotations

import os
from pathlib import Path


DEFAULT_MODEL_CONFIG = {
    "api_base_url": "https://api.openai.com/v1",
    "api_key": "",
    "chat_model": "gpt-4o-mini",
    "vision_model": "gpt-4o-mini",
}

ALIASES = {
    "api_base_url": "api_base_url",
    "base_url": "api_base_url",
    "openai_base_url": "api_base_url",
    "openai_api_base": "api_base_url",
    "api_key": "api_key",
    "openai_api_key": "api_key",
    "llm_model": "chat_model",
    "chat_llm_model": "chat_model",
    "chat_model": "chat_model",
    "vision_model": "vision_model",
    "image_model": "vision_model",
    "recognition_model": "vision_model",
    "ocr_model": "vision_model",
}


def default_config_path() -> Path:
    env_path = os.getenv("AI_MODEL_CONFIG_PATH", "").strip()
    if env_path:
        return Path(env_path)
    return Path(__file__).resolve().parent.parent / "data" / "ai_models.txt"


def ensure_model_config_file(path: str | Path | None = None) -> Path:
    config_path = Path(path) if path else default_config_path()
    config_path.parent.mkdir(parents=True, exist_ok=True)
    if not config_path.exists():
        config_path.write_text(
            "# Cat Agent model configuration\n"
            "# One KEY=VALUE per line. Lines beginning with # are ignored.\n"
            "API_BASE_URL=https://api.openai.com/v1\n"
            "API_KEY=\n"
            "CHAT_MODEL=gpt-4o-mini\n"
            "VISION_MODEL=gpt-4o-mini\n",
            encoding="utf-8",
        )
    return config_path


def load_model_config(path: str | Path | None = None) -> dict[str, str]:
    config_path = ensure_model_config_file(path)
    config: dict[str, str] = dict(DEFAULT_MODEL_CONFIG)
    for raw_line in config_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        normalized_key = ALIASES.get(key.strip().lower())
        if not normalized_key:
            continue
        config[normalized_key] = value.strip()
    if not config.get("api_key"):
        config["api_key"] = os.getenv("OPENAI_API_KEY", "").strip()
    if not config.get("api_base_url"):
        config["api_base_url"] = (
            os.getenv("OPENAI_BASE_URL", "").strip()
            or os.getenv("OPENAI_API_BASE", "").strip()
            or DEFAULT_MODEL_CONFIG["api_base_url"]
        )
    return config


def get_api_base_url(path: str | Path | None = None) -> str:
    return load_model_config(path).get("api_base_url", DEFAULT_MODEL_CONFIG["api_base_url"])


def get_api_key(path: str | Path | None = None) -> str:
    return load_model_config(path).get("api_key", DEFAULT_MODEL_CONFIG["api_key"])


def get_chat_model(path: str | Path | None = None) -> str:
    return load_model_config(path).get("chat_model", DEFAULT_MODEL_CONFIG["chat_model"])


def get_vision_model(path: str | Path | None = None) -> str:
    return load_model_config(path).get("vision_model", DEFAULT_MODEL_CONFIG["vision_model"])
