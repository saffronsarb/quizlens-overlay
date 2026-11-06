import json
import os
from pathlib import Path

CONFIG_FILE = Path(__file__).parent / "config.json"

DEFAULT_CONFIG = {
    "provider": "ollama",  # "ollama", "qwen", or "gemini"
    "api_key": "",
    "ollama_api_key": "",
    "ollama_base_url": "http://localhost:11434/v1",
    "ollama_model": "llama3.2-vision",
    "qwen_api_key": "",
    "qwen_base_url": "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
    "qwen_model": "qwen-vl-max",
    "gemini_api_key": "",
    "gemini_model": "gemini-3.8-flash",
    "model": "llama3.2-vision",
    "opacity": 0.18,
    "font_size": 8,
    "auto_copy": True,
    "always_on_top": True,
    "compact_mode": False,
    "glass_mode": False,
    "hide_from_taskbar": True,
    "auto_fallback_ollama": True,
    "click_through": False,
    "window_x": 100,
    "window_y": 100,
    "window_width": 200,
    "window_height": 200
}

def load_config() -> dict:
    """Load configuration from config.json or environment variables."""
    config = DEFAULT_CONFIG.copy()
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                saved = json.load(f)
                config.update(saved)
        except Exception as e:
            print(f"Error loading config: {e}")

    # Fallbacks for specific providers
    prov = config.get("provider", "ollama")
    if prov == "ollama":
        if not config.get("ollama_api_key"):
            config["ollama_api_key"] = os.environ.get("OLLAMA_API_KEY", "")
        if not config.get("api_key"):
            config["api_key"] = config.get("ollama_api_key", "")
        if not config.get("model"):
            config["model"] = config.get("ollama_model", "llama3.2-vision")

    elif prov == "qwen":
        if not config.get("qwen_api_key"):
            config["qwen_api_key"] = os.environ.get("DASHSCOPE_API_KEY") or os.environ.get("QWEN_API_KEY", "")
        if not config.get("api_key"):
            config["api_key"] = config.get("qwen_api_key", "")
        if not config.get("model"):
            config["model"] = config.get("qwen_model", "qwen-vl-max")

    elif prov == "gemini":
        if not config.get("gemini_api_key"):
            config["gemini_api_key"] = os.environ.get("GEMINI_API_KEY", "")
        if not config.get("api_key"):
            config["api_key"] = config.get("gemini_api_key", "")
        if not config.get("model"):
            config["model"] = config.get("gemini_model", "gemini-3.8-flash")

    return config

def save_config(config: dict) -> bool:
    """Save configuration dictionary to config.json."""
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2)
        return True
    except Exception as e:
        print(f"Error saving config: {e}")
        return False
