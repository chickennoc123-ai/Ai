"""LLM client abstraction used by the Research and Meta agents.

Four providers are supported.  ``heuristic`` is the default: it needs no API
key and no network, and answers from local templates so the platform stays
fully functional offline.  The other three call a real model over HTTPS.
"""

from __future__ import annotations

import json
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional

from utils.config import Config, get_config
from utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class LLMResponse:
    """Result of a completion call."""

    text: str
    provider: str
    model: str
    latency_ms: float = 0.0
    tokens: int = 0
    error: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        """``True`` when the call produced usable text."""
        return bool(self.text) and not self.error

    def as_json(self) -> Optional[Any]:
        """Parse the response as JSON, tolerating markdown code fences."""
        text = self.text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[-1].rsplit("```", 1)[0]
        try:
            return json.loads(text)
        except ValueError:
            return None


class LLMClient(ABC):
    """Interface implemented by every LLM provider."""

    provider: str = "base"

    def __init__(self, model: str, temperature: float = 0.4, max_tokens: int = 2000, timeout: int = 60) -> None:
        """Store generation parameters."""
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout = timeout

    @abstractmethod
    async def complete(self, prompt: str, system: Optional[str] = None) -> LLMResponse:
        """Return a completion for ``prompt``."""

    async def close(self) -> None:
        """Release provider resources."""


class HeuristicLLM(LLMClient):
    """Offline provider that answers from deterministic templates.

    It never fabricates market analysis: responses are derived from the
    structured context embedded in the prompt, so downstream code paths (JSON
    parsing, code validation) are exercised exactly as with a real model.
    """

    provider = "heuristic"

    def __init__(self, model: str = "heuristic-v1", **kwargs: Any) -> None:
        """Initialise the offline provider."""
        super().__init__(model=model, **kwargs)

    async def complete(self, prompt: str, system: Optional[str] = None) -> LLMResponse:
        """Return a short templated answer describing what was asked."""
        started = time.perf_counter()
        lowered = prompt.lower()
        if "json" in lowered:
            text = json.dumps(
                {
                    "provider": self.provider,
                    "note": "Offline heuristic provider - configure llm.provider for model output",
                }
            )
        else:
            text = (
                "Heuristic provider active. Configure `llm.provider` (anthropic, openai or "
                "ollama) with the matching API key to enable model generated content."
            )
        return LLMResponse(
            text=text,
            provider=self.provider,
            model=self.model,
            latency_ms=(time.perf_counter() - started) * 1000,
        )


class _HTTPLLM(LLMClient):
    """Shared aiohttp plumbing for the HTTP based providers."""

    def __init__(self, api_key: str, **kwargs: Any) -> None:
        """Store the API key and prepare the lazy session."""
        super().__init__(**kwargs)
        self.api_key = api_key
        self._session: Any = None

    async def _get_session(self) -> Any:
        """Create the aiohttp session on first use."""
        if self._session is None or self._session.closed:
            import aiohttp

            self._session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=self.timeout))
        return self._session

    async def close(self) -> None:
        """Close the aiohttp session."""
        if self._session is not None and not self._session.closed:
            await self._session.close()
        self._session = None

    async def _post(self, url: str, headers: Mapping[str, str], payload: Mapping[str, Any]) -> Dict[str, Any]:
        """POST JSON and return the decoded response."""
        session = await self._get_session()
        async with session.post(url, headers=dict(headers), json=dict(payload)) as response:
            body = await response.json(content_type=None)
            if response.status >= 400:
                raise RuntimeError(f"{self.provider} error {response.status}: {str(body)[:200]}")
            return body


class AnthropicLLM(_HTTPLLM):
    """Anthropic Messages API provider."""

    provider = "anthropic"
    endpoint = "https://api.anthropic.com/v1/messages"

    async def complete(self, prompt: str, system: Optional[str] = None) -> LLMResponse:
        """Call the Messages API and return the first text block."""
        started = time.perf_counter()
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        payload: Dict[str, Any] = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            "messages": [{"role": "user", "content": prompt}],
        }
        if system:
            payload["system"] = system
        try:
            body = await self._post(self.endpoint, headers, payload)
            blocks = body.get("content") or []
            text = "".join(block.get("text", "") for block in blocks if block.get("type") == "text")
            usage = body.get("usage") or {}
            return LLMResponse(
                text=text,
                provider=self.provider,
                model=self.model,
                latency_ms=(time.perf_counter() - started) * 1000,
                tokens=int(usage.get("input_tokens", 0)) + int(usage.get("output_tokens", 0)),
            )
        except Exception as exc:  # noqa: BLE001 - surfaced to the caller as an error response
            logger.warning("Anthropic completion failed", error=str(exc))
            return LLMResponse("", self.provider, self.model, error=str(exc))


class OpenAILLM(_HTTPLLM):
    """OpenAI Chat Completions provider."""

    provider = "openai"
    endpoint = "https://api.openai.com/v1/chat/completions"

    async def complete(self, prompt: str, system: Optional[str] = None) -> LLMResponse:
        """Call the Chat Completions API and return the first choice."""
        started = time.perf_counter()
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        messages: List[Dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }
        try:
            body = await self._post(self.endpoint, headers, payload)
            choices = body.get("choices") or [{}]
            text = str(choices[0].get("message", {}).get("content", ""))
            usage = body.get("usage") or {}
            return LLMResponse(
                text=text,
                provider=self.provider,
                model=self.model,
                latency_ms=(time.perf_counter() - started) * 1000,
                tokens=int(usage.get("total_tokens", 0)),
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("OpenAI completion failed", error=str(exc))
            return LLMResponse("", self.provider, self.model, error=str(exc))


class OllamaLLM(_HTTPLLM):
    """Local Ollama provider (Llama, Mistral, ...)."""

    provider = "ollama"

    def __init__(self, base_url: str = "http://localhost:11434", **kwargs: Any) -> None:
        """Store the Ollama base URL."""
        super().__init__(api_key="", **kwargs)
        self.base_url = base_url.rstrip("/")

    async def complete(self, prompt: str, system: Optional[str] = None) -> LLMResponse:
        """Call the Ollama generate endpoint."""
        started = time.perf_counter()
        payload: Dict[str, Any] = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": self.temperature},
        }
        if system:
            payload["system"] = system
        try:
            body = await self._post(f"{self.base_url}/api/generate", {"Content-Type": "application/json"}, payload)
            return LLMResponse(
                text=str(body.get("response", "")),
                provider=self.provider,
                model=self.model,
                latency_ms=(time.perf_counter() - started) * 1000,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Ollama completion failed", error=str(exc))
            return LLMResponse("", self.provider, self.model, error=str(exc))


def create_llm_client(config: Optional[Config] = None) -> LLMClient:
    """Build the configured LLM client.

    Falls back to :class:`HeuristicLLM` whenever the selected provider is
    unavailable (missing key, unknown name), so callers never have to branch.
    """
    cfg = config or get_config()
    import os

    provider = str(cfg.get("llm.provider", "heuristic")).lower()
    model = str(cfg.get("llm.model", "claude-sonnet-5"))
    common = {
        "temperature": cfg.get_float("llm.temperature", 0.4),
        "max_tokens": cfg.get_int("llm.max_tokens", 2000),
        "timeout": cfg.get_int("llm.timeout", 60),
    }

    if provider == "anthropic":
        key = os.environ.get("ANTHROPIC_API_KEY", "")
        if key:
            return AnthropicLLM(api_key=key, model=model, **common)
        logger.warning("ANTHROPIC_API_KEY missing, using the heuristic LLM provider")
    elif provider == "openai":
        key = os.environ.get("OPENAI_API_KEY", "")
        if key:
            return OpenAILLM(api_key=key, model=model, **common)
        logger.warning("OPENAI_API_KEY missing, using the heuristic LLM provider")
    elif provider == "ollama":
        return OllamaLLM(base_url=os.environ.get("OLLAMA_URL", "http://localhost:11434"), model=model, **common)
    elif provider != "heuristic":
        logger.warning("Unknown LLM provider, using the heuristic provider", provider=provider)
    return HeuristicLLM(**common)
