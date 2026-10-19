"""Thin Ollama Cloud chat wrapper, shared by the ATS scorer (T3), selector (T4)
and improver (T5). Deterministic by default (temperature 0)."""

import json
import re

from ollama import Client

from app.core import config


def _client() -> Client:
    headers = {"Authorization": f"Bearer {config.OLLAMA_API_KEY}"} if config.OLLAMA_API_KEY else None
    return Client(host=config.OLLAMA_HOST, headers=headers)


def _loads(text: str) -> dict:
    """Parse JSON from an LLM reply. gemma4:31b-cloud ignores Ollama's `format`
    enforcement and often wraps JSON in ```fences``` or prose, so pull the JSON
    body out before decoding."""
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    body = m.group(1) if m else text
    m = re.search(r"[\[{].*[\]}]", body, re.S)  # outermost object/array
    return json.loads(m.group(0) if m else body)


def chat(messages: list[dict], *, format: dict | None = None, model: str | None = None) -> str | dict:
    """Send a chat request. When `format` (a pydantic JSON schema) is given,
    returns the parsed JSON dict; otherwise returns the raw text content."""
    with _client() as client:  # closes its connection; one leaked per call before (T32)
        resp = client.chat(
            model=model or config.OLLAMA_MODEL,
            messages=messages,
            format=format,
            options={"temperature": 0, "num_ctx": 32768},
        )
    content = resp["message"]["content"]
    return _loads(content) if format else content
