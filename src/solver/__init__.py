"""
AI Solver Module.

Exports:
- SolutionRequest, SolutionResponse
- ProviderError, ProviderErrorKind
- BaseAIProvider, GroqProvider, GeminiProvider
- PromptBuilder
- SolutionValidator
- AISolverEngine
"""

from .models import (
    SolutionRequest,
    SolutionResponse,
    ProviderError,
    ProviderErrorKind,
)
from .provider import (
    BaseAIProvider,
    GroqProvider,
    GeminiProvider,
)
from .prompt import PromptBuilder
from .validator import SolutionValidator
from .engine import AISolverEngine

__all__ = [
    "SolutionRequest",
    "SolutionResponse",
    "ProviderError",
    "ProviderErrorKind",
    "BaseAIProvider",
    "GroqProvider",
    "GeminiProvider",
    "PromptBuilder",
    "SolutionValidator",
    "AISolverEngine",
]
