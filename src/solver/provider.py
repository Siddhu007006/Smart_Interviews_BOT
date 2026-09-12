"""
AI Provider abstraction and implementations (Groq, Gemini).

Enforces:
- Zero hardcoded model strings (models are injected via configuration)
- Structured error classification (AUTH_FAILURE, RATE_LIMIT, TIMEOUT, UNAVAILABLE, etc.)
- Strict separation between transient errors (for fallback) and invalid requests (fail-loud)
"""

from abc import ABC, abstractmethod
import asyncio
import re
from typing import Dict, Any, Optional
import httpx

from src.solver.models import SolutionRequest, ProviderError, ProviderErrorKind
from src.utils.logging_config import get_logger

logger = get_logger(__name__)


class BaseAIProvider(ABC):
    """Abstract base class for AI LLM providers."""

    def __init__(self, name: str, api_key: str, model: str, timeout_seconds: float = 60.0):
        if not api_key or not api_key.strip():
            raise ProviderError(
                kind=ProviderErrorKind.AUTH_FAILURE,
                provider_name=name,
                message=f"Missing API key for provider '{name}'"
            )
        if not model or not model.strip():
            raise ProviderError(
                kind=ProviderErrorKind.INVALID_REQUEST,
                provider_name=name,
                message=f"Missing model name for provider '{name}'"
            )

        self.name = name
        self.api_key = api_key.strip()
        self.model = model.strip()
        self.timeout_seconds = timeout_seconds

    @abstractmethod
    async def generate_code(self, prompt: str) -> str:
        """Execute inference request and return raw generated text."""
        pass

    def _mask_secrets(self, text: str) -> str:
        """Mask API keys and sensitive tokens from error text and logs.

        Available on all providers via base class — never call this before
        calling super().__init__() since it depends on self.api_key.
        """
        if not text:
            return ""
        if self.api_key and len(self.api_key) > 4:
            text = text.replace(self.api_key, "[REDACTED_API_KEY]")
        text = re.sub(r"gsk_[A-Za-z0-9_-]{10,}", "[REDACTED_GROQ_KEY]", text)
        text = re.sub(r"AIza[A-Za-z0-9_-]{10,}", "[REDACTED_GEMINI_KEY]", text)
        return text


class GroqProvider(BaseAIProvider):
    """Groq API provider implementation (OpenAI-compatible chat completions API)."""

    def __init__(self, api_key: str, model: str, timeout_seconds: float = 60.0):
        super().__init__(name="groq", api_key=api_key, model=model, timeout_seconds=timeout_seconds)
        self.endpoint = "https://api.groq.com/openai/v1/chat/completions"

    async def generate_code(self, prompt: str) -> str:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": "You are an expert competitive programmer. Output only code."},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.2,
        }

        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                response = await client.post(self.endpoint, headers=headers, json=payload)

            if response.status_code == 200:
                data = response.json()
                choices = data.get("choices", [])
                if not choices:
                    raise ProviderError(ProviderErrorKind.INVALID_RESPONSE, self.name, "No choices in response", 200)
                content = choices[0].get("message", {}).get("content", "")
                if not content:
                    raise ProviderError(ProviderErrorKind.INVALID_RESPONSE, self.name, "Empty message content", 200)
                return content

            self._handle_http_error(response.status_code, response.text)

        except httpx.TimeoutException as e:
            raise ProviderError(ProviderErrorKind.TIMEOUT, self.name, f"Request timed out: {e}") from e
        except httpx.RequestError as e:
            raise ProviderError(ProviderErrorKind.UNAVAILABLE, self.name, f"Network connection error: {e}") from e

    def _handle_http_error(self, status: int, text: str) -> None:
        masked_text = self._mask_secrets(text)
        if status in (401, 403):
            raise ProviderError(ProviderErrorKind.AUTH_FAILURE, self.name, masked_text, status)
        if status == 429:
            raise ProviderError(ProviderErrorKind.RATE_LIMIT, self.name, masked_text, status)
        if status == 400:
            raise ProviderError(ProviderErrorKind.INVALID_REQUEST, self.name, masked_text, status)
        if status >= 500:
            raise ProviderError(ProviderErrorKind.UNAVAILABLE, self.name, masked_text, status)
        raise ProviderError(ProviderErrorKind.INVALID_RESPONSE, self.name, masked_text, status)


class GeminiProvider(BaseAIProvider):
    """Google Gemini API provider implementation."""

    def __init__(self, api_key: str, model: str, timeout_seconds: float = 60.0):
        super().__init__(name="gemini", api_key=api_key, model=model, timeout_seconds=timeout_seconds)
        self.endpoint_template = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

    async def generate_code(self, prompt: str) -> str:
        url = self.endpoint_template.format(model=self.model)
        headers = {
            "Content-Type": "application/json",
            "x-goog-api-key": self.api_key,
        }
        payload = {
            "contents": [
                {
                    "parts": [{"text": prompt}]
                }
            ],
            "generationConfig": {
                "temperature": 0.2,
            }
        }

        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                response = await client.post(url, headers=headers, json=payload)

            if response.status_code == 200:
                data = response.json()
                candidates = data.get("candidates", [])
                if not candidates:
                    raise ProviderError(ProviderErrorKind.INVALID_RESPONSE, self.name, "No candidates in response", 200)
                parts = candidates[0].get("content", {}).get("parts", [])
                if not parts or not parts[0].get("text"):
                    raise ProviderError(ProviderErrorKind.INVALID_RESPONSE, self.name, "Empty candidate parts", 200)
                return parts[0]["text"]

            self._handle_http_error(response.status_code, response.text)

        except httpx.TimeoutException as e:
            raise ProviderError(ProviderErrorKind.TIMEOUT, self.name, f"Request timed out: {e}") from e
        except httpx.RequestError as e:
            raise ProviderError(ProviderErrorKind.UNAVAILABLE, self.name, f"Network connection error: {e}") from e

    def _handle_http_error(self, status: int, text: str) -> None:
        masked_text = self._mask_secrets(text)
        if status in (401, 403):
            raise ProviderError(ProviderErrorKind.AUTH_FAILURE, self.name, masked_text, status)
        if status == 429:
            raise ProviderError(ProviderErrorKind.RATE_LIMIT, self.name, masked_text, status)
        if status == 400:
            # Some providers (e.g. Gemini) return 400 for invalid/expired API keys
            # instead of 401. Detect auth-specific signals in the body.
            text_lower = masked_text.lower()
            if any(sig in text_lower for sig in (
                "api_key_invalid", "invalid_api_key", "api key not valid",
                "api key is invalid", "authentication", "unauthorized",
            )):
                raise ProviderError(ProviderErrorKind.AUTH_FAILURE, self.name, masked_text, status)
            raise ProviderError(ProviderErrorKind.INVALID_REQUEST, self.name, masked_text, status)
        if status in (404,):
            # 404 can mean model not found — treat as INVALID_RESPONSE so fallback occurs
            text_lower = masked_text.lower()
            if "model" in text_lower and ("not found" in text_lower or "does not exist" in text_lower):
                raise ProviderError(ProviderErrorKind.INVALID_RESPONSE, self.name, masked_text, status)
            raise ProviderError(ProviderErrorKind.INVALID_RESPONSE, self.name, masked_text, status)
        if status >= 500:
            raise ProviderError(ProviderErrorKind.UNAVAILABLE, self.name, masked_text, status)
        raise ProviderError(ProviderErrorKind.INVALID_RESPONSE, self.name, masked_text, status)
