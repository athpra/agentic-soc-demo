"""
Thin wrapper around the OpenAI-compatible client for calling models served by
Cloudera AI Inference Service, plus small helpers for timing and JSON
extraction that the rest of the app relies on.
"""

import json
import re
import time
from dataclasses import dataclass, field
from typing import Any, Optional

from openai import OpenAI

from src.config import ModelConfig, get_access_token


@dataclass
class ChatResult:
    text: str
    latency_s: float
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    total_tokens: Optional[int] = None
    model: str = ""
    error: Optional[str] = None
    raw: Any = field(default=None, repr=False)
    # Populated by callers (see analysis.strip_reasoning_preamble) when a
    # reasoning-tuned model inlines its chain-of-thought ahead of the real
    # answer instead of returning it in a separate field.
    reasoning: Optional[str] = None


def _client_for(model_cfg: ModelConfig) -> OpenAI:
    # A fresh client is cheap and guarantees we always use a current token,
    # since Cloudera AI Workbench rotates the underlying JWT periodically.
    return OpenAI(base_url=model_cfg.base_url, api_key=get_access_token())


def chat(
    model_cfg: ModelConfig,
    messages: list[dict],
    *,
    temperature: float = 0.2,
    max_tokens: int = 1024,
    timeout: float = 60.0,
) -> ChatResult:
    """Call one Cloudera AI Inference chat-completions endpoint and time it."""
    start = time.perf_counter()
    try:
        client = _client_for(model_cfg)
        resp = client.chat.completions.create(
            model=model_cfg.model_id,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=timeout,
        )
        latency = time.perf_counter() - start
        choice_text = resp.choices[0].message.content or ""
        usage = getattr(resp, "usage", None)
        return ChatResult(
            text=choice_text,
            latency_s=latency,
            prompt_tokens=getattr(usage, "prompt_tokens", None) if usage else None,
            completion_tokens=getattr(usage, "completion_tokens", None) if usage else None,
            total_tokens=getattr(usage, "total_tokens", None) if usage else None,
            model=model_cfg.label,
            raw=resp,
        )
    except Exception as exc:  # noqa: BLE001 - surface any endpoint/auth error to the UI
        latency = time.perf_counter() - start
        return ChatResult(text="", latency_s=latency, model=model_cfg.label, error=str(exc))


_JSON_BLOCK_RE = re.compile(r"\{.*\}|\[.*\]", re.DOTALL)


def extract_json(text: str):
    """Best-effort extraction of a JSON object/array from a model response.

    Models are asked to reply with pure JSON, but small instruct models
    occasionally wrap it in prose or a markdown fence -- this strips that
    off rather than failing the whole triage batch on a formatting slip.
    """
    text = text.strip()
    fence = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    match = _JSON_BLOCK_RE.search(text)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass
    return None
