"""
AI Solver Engine with managed fallback chain and error classification.

Chain order:
  Groq -> Gemini

Enforces:
- Zero provider model IDs in Python source code (reads strictly from ConfigManager)
- Selective fallback: transient errors fallback, invalid requests fail-loud immediately
- Deterministic cleaning and validation via SolutionValidator
"""

import asyncio
from typing import List, Optional, Dict, Any

from src.solver.models import (
    SolutionRequest,
    SolutionResponse,
    ProviderError,
    ProviderErrorKind,
)
from src.solver.provider import (
    BaseAIProvider,
    GroqProvider,
    GeminiProvider,
)
from src.solver.prompt import PromptBuilder
from src.solver.validator import SolutionValidator
from src.utils.config import ConfigManager
from src.utils.errors import SolverError, ConfigError
from src.utils.logging_config import get_logger

logger = get_logger(__name__)


class AISolverEngine:
    """Orchestrates AI code generation across provider fallback chain."""

    def __init__(self, config: ConfigManager, providers: Optional[List[BaseAIProvider]] = None):
        self.config = config
        if providers is not None:
            self.providers = providers
        else:
            self.providers = self._init_providers_from_config()

    def _init_providers_from_config(self) -> List[BaseAIProvider]:
        """
        Initialize provider chain based on configuration.

        Skips providers that have no API key OR no model configured (with a warning).
        Only fails loudly (via ConfigError) if NO providers at all could be initialized.
        """
        chain_order = self.config.get("solver.fallback_chain", ["groq", "gemini"])
        initialized: List[BaseAIProvider] = []

        for name in chain_order:
            provider_name = name.lower().strip()

            # Get API key first — if not configured, provider is simply not enabled; skip silently.
            api_key = (
                self.config.get(f"ai_providers.{provider_name}.api_key")
                or self.config.get(f"{provider_name}_api_key")
                or self.config.get(f"solver.{provider_name}_api_key")
            )
            if not api_key:
                logger.debug(
                    f"No API key configured for provider '{provider_name}'; skipping from active chain."
                )
                continue

            # Get model ID — if API key is set but model is missing, fail loudly.
            # (Misconfiguration: developer added key but forgot model env var.)
            try:
                model = self.config.get_provider_model(provider_name)
            except Exception:
                raise ConfigError(
                    f"Missing required model ID for provider '{provider_name}'. "
                    f"Set {provider_name.upper()}_MODEL environment variable or configure "
                    f"ai_providers.{provider_name}.model in config."
                )

            timeout = float(self.config.get("solver.timeout_seconds", 60.0))

            if provider_name == "groq":
                initialized.append(GroqProvider(api_key=api_key, model=model, timeout_seconds=timeout))
            elif provider_name == "gemini":
                initialized.append(GeminiProvider(api_key=api_key, model=model, timeout_seconds=timeout))
            else:
                logger.warning(f"Unknown provider name '{provider_name}' in fallback chain")

            logger.info(f"✓ Initialized AI provider: {provider_name} (model: {model})")

        if not initialized:
            logger.warning("No AI providers could be initialized with valid API keys and models")

        return initialized


    async def solve(self, request: SolutionRequest) -> SolutionResponse:
        """
        Generate or repair a solution for the given problem request.

        Attempts providers in order. Falls back on transient errors.
        Fails immediately on invalid requests.

        Raises:
            SolverError: If all providers fail, or if an unrecoverable request error occurs.
        """
        if not self.providers:
            raise SolverError("No AI providers available in solver engine")

        prompt = PromptBuilder.build_prompt(request)
        last_error: Optional[Exception] = None

        for idx, provider in enumerate(self.providers):
            logger.info(
                f"Attempting solution generation with provider '{provider.name}' (model: '{provider.model}')",
                extra={"attempt": request.attempt_number, "problem_id": request.problem_id}
            )

            try:
                raw_response = await provider.generate_code(prompt)
                clean_code = SolutionValidator.clean_and_validate(raw_response, request.language)

                logger.info(
                    f"Successfully generated clean solution via '{provider.name}' ({len(clean_code)} chars)"
                )
                return SolutionResponse(
                    code=clean_code,
                    language=request.language,
                    provider=provider.name,
                    model=provider.model,
                    raw_response=raw_response,
                )

            except ProviderError as e:
                last_error = e
                # CONSTRAINT: INVALID_REQUEST indicates a malformed prompt/body created by our code
                # Do NOT silently fallback to hide programming errors!
                if e.kind == ProviderErrorKind.INVALID_REQUEST:
                    logger.error(f"Provider '{provider.name}' rejected request as INVALID: {e}")
                    raise

                # AUTH_FAILURE = bad/expired credentials for THIS provider; log and continue to next.
                if e.kind == ProviderErrorKind.AUTH_FAILURE:
                    logger.warning(
                        f"Provider '{provider.name}' AUTH_FAILURE (bad/expired key): {e.message}. "
                        f"Falling back to next provider."
                    )
                    continue

                logger.warning(
                    f"Provider '{provider.name}' failed with {e.kind.value}: {e.message}. "
                    f"Will fallback to next provider if available."
                )

            except Exception as e:
                last_error = e
                logger.warning(f"Unexpected error with provider '{provider.name}': {e}. Falling back.")

        raise SolverError(f"All AI providers exhausted without a successful solution. Last error: {last_error}") from last_error
