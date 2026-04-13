"""
workers/analyst/ollama_patch.py

Routes LLM calls to the local Ollama instance (qwen2.5:3b) via litellm's
OpenAI-compatible adapter.

How it works:
    Ollama exposes an OpenAI-compatible API at /v1. We point litellm's
    OpenAI base URL to Ollama and set the model to qwen2.5:3b. The analyst
    worker uses call_ollama() directly for all inference.

Usage:
    Import this module before making any LLM calls. The patch is applied
    at module load time.
"""

import os
import logging

logger = logging.getLogger(__name__)

OLLAMA_HOST  = os.getenv("OLLAMA_HOST", "http://ollama:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:3b")

# ── Set env vars that litellm reads at import time ────────────────────────────
# Ollama's OpenAI-compatible endpoint lives at /v1
os.environ.setdefault("OPENAI_API_BASE", f"{OLLAMA_HOST}/v1")
os.environ.setdefault("OPENAI_API_KEY",  "ollama")   # litellm requires a key, value ignored by Ollama

# ── Patch litellm if already imported ─────────────────────────────────────────
try:
    import litellm
    litellm.api_base          = f"{OLLAMA_HOST}/v1"
    litellm.drop_params       = True    # Ignore unsupported params (e.g. logprobs)
    litellm.request_timeout   = 120
    litellm.max_tokens        = 512
    logger.info(f"ollama_patch: litellm redirected → {OLLAMA_HOST}/v1 (model: {OLLAMA_MODEL})")
except ImportError:
    logger.warning("ollama_patch: litellm not installed — patch skipped")


def get_ollama_model() -> str:
    """Return the litellm model string for Ollama."""
    return f"openai/{OLLAMA_MODEL}"


def call_ollama(prompt: str, system: str = "") -> str:
    """
    Direct litellm call to Ollama.

    Returns the model's text response, or an error string on failure.
    """
    try:
        import litellm
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        response = litellm.completion(
            model    = get_ollama_model(),
            messages = messages,
            api_base = f"{OLLAMA_HOST}/v1",
            api_key  = "ollama",
            timeout  = 120,
            max_tokens = 512,
        )
        return response.choices[0].message.content or ""
    except Exception as exc:
        logger.error(f"ollama_patch.call_ollama failed: {exc}")
        return f"[LLM unavailable: {type(exc).__name__}]"
