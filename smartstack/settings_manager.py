"""
settings_manager.py — Persistent settings for SmartStack.

Stored in settings.json (next to app.py). Defaults apply on first run.
"""

import copy
import json
import logging
import os
from datetime import date
from typing import Optional

logger = logging.getLogger(__name__)

SETTINGS_PATH = os.path.join(os.path.dirname(__file__), "settings.json")
GROQ_FREE_TIER_DAILY_LIMIT = 100_000

DEFAULTS: dict = {
    "text_model": {
        "use_custom": False,
        "model": "groq/llama-3.3-70b-versatile",
        "api_key": "",
        "base_url": "",
    },
    "vision_model": {
        "use_custom": False,
        "model": "groq/meta-llama/llama-4-scout-17b-16e-instruct",
        "api_key": "",
        "base_url": "",
    },
    "folders": {
        "Study": "Study",
        "College Admin": "College Admin",
        "Personal/Fun": "Personal/Fun",
        "Miscellaneous": "Miscellaneous",
    },
    "processing": {
        "max_pages": 10,
        "delay_seconds": 2,
    },
    "sheets": {
        "sheet_name": "SmartStack Log",
    },
    "preset": "light",
    "colors": {
        "primary":   "#FFFFFF",
        "secondary": "#F5EDD8",
        "button":    "#8B7355",
    },
    "directives": "",

    "token_usage": {
        "date": "",
        "total": 0,
    },
}


def load_settings() -> dict:
    if os.path.exists(SETTINGS_PATH):
        try:
            with open(SETTINGS_PATH) as f:
                saved = json.load(f)
            settings = _deep_merge(DEFAULTS, saved)
        except Exception as exc:
            logger.warning("Could not load settings.json (%s) — using defaults.", exc)
            settings = copy.deepcopy(DEFAULTS)
    else:
        settings = copy.deepcopy(DEFAULTS)

    # Migrate legacy directives.txt
    if not settings["directives"]:
        legacy = os.path.join(os.path.dirname(__file__), "directives.txt")
        if os.path.exists(legacy):
            try:
                settings["directives"] = open(legacy).read().strip()
            except Exception:
                pass

    return settings


def save_settings(settings: dict) -> None:
    with open(SETTINGS_PATH, "w") as f:
        json.dump(settings, f, indent=2)


def _deep_merge(base: dict, override: dict) -> dict:
    result = dict(base)
    for k, v in override.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = _deep_merge(result[k], v)
        else:
            result[k] = v
    return result


def get_text_model_kwargs(settings: dict) -> dict:
    tm = settings["text_model"]
    if tm.get("use_custom") and tm.get("model") and tm.get("api_key"):
        kwargs: dict = {"model": tm["model"], "api_key": tm["api_key"]}
        if tm.get("base_url"):
            kwargs["api_base"] = tm["base_url"]
        return kwargs
    from config import GROQ_API_KEY
    return {"model": "groq/llama-3.3-70b-versatile", "api_key": GROQ_API_KEY}


def get_vision_model_kwargs(settings: dict) -> dict:
    vm = settings["vision_model"]
    if vm.get("use_custom") and vm.get("model") and vm.get("api_key"):
        kwargs: dict = {"model": vm["model"], "api_key": vm["api_key"]}
        if vm.get("base_url"):
            kwargs["api_base"] = vm["base_url"]
        return kwargs
    from config import GROQ_API_KEY
    return {"model": "groq/meta-llama/llama-4-scout-17b-16e-instruct", "api_key": GROQ_API_KEY}


def get_category_folders(settings: dict) -> dict:
    return dict(settings.get("folders", DEFAULTS["folders"]))


def validate_model_config(settings: dict) -> Optional[str]:
    """Return error string if model config is broken, else None."""
    for label, key in [("Text model", "text_model"), ("Vision model", "vision_model")]:
        cfg = settings[key]
        if cfg.get("use_custom"):
            if not cfg.get("model"):
                return f"{label}: please enter a model name in Settings."
            if not cfg.get("api_key"):
                return f"Please enter an API key for your custom {label.lower()} in Settings."
    # Default path: Groq key must exist
    if not settings["text_model"].get("use_custom") or not settings["vision_model"].get("use_custom"):
        try:
            from config import GROQ_API_KEY
            if not GROQ_API_KEY:
                return "GROQ_API_KEY is not set. Get a free key at https://console.groq.com"
        except ImportError:
            pass
    return None


def track_tokens(settings: dict, tokens: int) -> dict:
    today = str(date.today())
    if settings["token_usage"].get("date") != today:
        settings["token_usage"] = {"date": today, "total": 0}
    settings["token_usage"]["total"] = settings["token_usage"].get("total", 0) + tokens
    return settings
