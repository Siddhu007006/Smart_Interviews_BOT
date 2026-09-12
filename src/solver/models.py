"""
Data models and error types for the AI solving pipeline.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional, Dict, Any

from src.hive.problem_detail import SampleTestCase
from src.utils.errors import SolverError


class ProviderErrorKind(str, Enum):
    """Classification of provider failures to govern fallback decisions."""
    AUTH_FAILURE = "AUTH_FAILURE"           # 401/403, invalid API key (non-retryable on same provider)
    RATE_LIMIT = "RATE_LIMIT"               # 429, quota exhausted (retryable with fallback)
    TIMEOUT = "TIMEOUT"                     # Request timeout (retryable with fallback)
    UNAVAILABLE = "UNAVAILABLE"             # 500, 502, 503, 504 server/network down (retryable with fallback)
    INVALID_RESPONSE = "INVALID_RESPONSE"   # Empty or corrupted response body (retryable with fallback)
    INVALID_REQUEST = "INVALID_REQUEST"     # 400 Bad Request, malformed prompt/body (programming error: do not fallback)


class ProviderError(SolverError):
    """Represents a categorized failure from an AI provider."""

    def __init__(
        self,
        kind: ProviderErrorKind,
        provider_name: str,
        message: str,
        status_code: Optional[int] = None
    ):
        self.kind = kind
        self.provider_name = provider_name
        self.status_code = status_code
        self.message = message
        super().__init__(f"[{provider_name}] {kind.value}: {message} (Status: {status_code})")

    @property
    def is_transient(self) -> bool:
        """Determines whether fallback to an alternative provider is warranted."""
        return self.kind in (
            ProviderErrorKind.RATE_LIMIT,
            ProviderErrorKind.TIMEOUT,
            ProviderErrorKind.UNAVAILABLE,
            ProviderErrorKind.INVALID_RESPONSE,
        )


@dataclass
class SolutionRequest:
    """Input specification for generating or repairing a solution."""
    problem_id: str
    title: str
    description: str
    input_format: str
    output_format: str
    constraints: str
    sample_cases: List[SampleTestCase] = field(default_factory=list)
    language: str = "C++"
    attempt_number: int = 1
    previous_code: Optional[str] = None
    previous_error: Optional[str] = None
    previous_verdict: Optional[str] = None


@dataclass
class SolutionResponse:
    """Output from an AI provider containing cleaned code and metadata."""
    code: str
    language: str
    provider: str
    model: str
    raw_response: str
