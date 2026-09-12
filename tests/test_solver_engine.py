"""
Unit tests for AI Solver Engine, Providers, PromptBuilder, and SolutionValidator (Step 5).

Strictly enforces:
- Zero hardcoded provider model strings in source or test code
- Selective fallback: transient errors trigger fallback, INVALID_REQUEST fails immediately
- Deterministic cleaning and sanity checking in SolutionValidator
- Prompt construction with iterative repair context
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

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
from src.solver.engine import AISolverEngine
from src.hive.problem_detail import SampleTestCase
from src.utils.config import ConfigManager
from src.utils.errors import SolverError, ConfigError


def make_dummy_request(language="C++", attempt_number=1, previous_code=None, previous_error=None):
    return SolutionRequest(
        problem_id="test-prob",
        title="Sum of Array",
        description="Compute sum of array elements.",
        input_format="First line N, second line elements.",
        output_format="Print sum.",
        constraints="1 <= N <= 10^5",
        sample_cases=[SampleTestCase(input_data="3\n1 2 3", output_data="6", explanation="1+2+3=6")],
        language=language,
        attempt_number=attempt_number,
        previous_code=previous_code,
        previous_error=previous_error,
        previous_verdict="Wrong Answer" if attempt_number > 1 else None
    )


# ---------------------------------------------------------
# SolutionValidator Tests
# ---------------------------------------------------------

def test_validator_strips_markdown_fences():
    """Verify code fences and language specifiers are stripped."""
    raw = "```cpp\n#include <iostream>\nint main() {\n    return 0;\n}\n```"
    cleaned = SolutionValidator.clean_and_validate(raw, "C++")
    assert cleaned == "#include <iostream>\nint main() {\n    return 0;\n}"


def test_validator_strips_conversational_prose():
    """Verify introductory and trailing conversational prose is stripped."""
    raw = """Here is the optimal C++ solution to solve this problem:

#include <iostream>
using namespace std;

int main() {
    cout << "hello\\n";
    return 0;
}

Explanation:
This solution runs in O(N) time and uses O(1) extra space.
"""
    cleaned = SolutionValidator.clean_and_validate(raw, "C++")
    assert cleaned.startswith("#include <iostream>")
    assert cleaned.endswith("return 0;\n}")
    assert "Here is the" not in cleaned
    assert "Explanation:" not in cleaned


def test_validator_enforces_structural_sanity_cpp():
    """Verify C++ code without a main function is rejected."""
    raw = "```cpp\n#include <iostream>\nint add(int a, int b) { return a + b; }\n```"
    with pytest.raises(SolverError, match="lacks a 'main' function"):
        SolutionValidator.clean_and_validate(raw, "C++")


def test_validator_enforces_structural_sanity_python():
    """Verify Python code with only comments is rejected."""
    raw = "```python\n# This is a comment\n# Another comment\n```"
    with pytest.raises(SolverError, match="contains only comments or whitespace"):
        SolutionValidator.clean_and_validate(raw, "Python")


def test_validator_empty_response_raises():
    """Verify empty provider response raises SolverError."""
    with pytest.raises(SolverError, match="empty"):
        SolutionValidator.clean_and_validate("   ", "C++")


# ---------------------------------------------------------
# PromptBuilder Tests
# ---------------------------------------------------------

def test_prompt_builder_initial_attempt():
    """Verify prompt formatting for first attempt."""
    req = make_dummy_request(language="C++", attempt_number=1)
    prompt = PromptBuilder.build_prompt(req)

    assert "Sum of Array" in prompt
    assert "Compute sum of array elements." in prompt
    assert "1 <= N <= 10^5" in prompt
    assert "Sample #1:" in prompt
    assert "1+2+3=6" in prompt
    assert "REPAIR INSTRUCTIONS" not in prompt


def test_prompt_builder_repair_attempt():
    """Verify prompt formatting includes repair context on subsequent attempts."""
    req = make_dummy_request(
        language="C++",
        attempt_number=2,
        previous_code="#include <iostream>\nint main() { return 1; }",
        previous_error="Wrong Answer on Sample Case #1"
    )
    prompt = PromptBuilder.build_prompt(req)

    assert "REPAIR INSTRUCTIONS" in prompt
    assert "Attempt: #2" in prompt
    assert "Wrong Answer on Sample Case #1" in prompt
    assert "int main() { return 1; }" in prompt


# ---------------------------------------------------------
# Provider & Fallback Tests
# ---------------------------------------------------------

@pytest.mark.asyncio
async def test_fallback_on_transient_rate_limit():
    """Verify engine falls back from primary (429) to secondary provider."""
    mock_config = MagicMock()
    # Provider 1: Groq fails with 429 RATE_LIMIT
    p1 = MagicMock(spec=BaseAIProvider)
    p1.name = "groq"
    p1.model = "model-a"
    p1.generate_code = AsyncMock(
        side_effect=ProviderError(ProviderErrorKind.RATE_LIMIT, "groq", "Too many requests", 429)
    )

    # Provider 2: Gemini succeeds
    p2 = MagicMock(spec=BaseAIProvider)
    p2.name = "gemini"
    p2.model = "model-b"
    p2.generate_code = AsyncMock(
        return_value="```cpp\n#include <iostream>\nint main() { return 0; }\n```"
    )

    engine = AISolverEngine(config=mock_config, providers=[p1, p2])
    req = make_dummy_request()
    resp = await engine.solve(req)

    assert resp.provider == "gemini"
    assert resp.model == "model-b"
    assert "int main()" in resp.code
    p1.generate_code.assert_called_once()
    p2.generate_code.assert_called_once()


@pytest.mark.asyncio
async def test_fallback_on_timeout():
    """Verify engine falls back on timeout."""
    mock_config = MagicMock()
    p1 = MagicMock(spec=BaseAIProvider)
    p1.name = "groq"
    p1.model = "model-a"
    p1.generate_code = AsyncMock(
        side_effect=ProviderError(ProviderErrorKind.TIMEOUT, "groq", "Timed out", 408)
    )

    p2 = MagicMock(spec=BaseAIProvider)
    p2.name = "gemini"
    p2.model = "model-b"
    p2.generate_code = AsyncMock(
        return_value="```cpp\n#include <iostream>\nint main() { return 0; }\n```"
    )

    engine = AISolverEngine(config=mock_config, providers=[p1, p2])
    req = make_dummy_request()
    resp = await engine.solve(req)

    assert resp.provider == "gemini"


@pytest.mark.asyncio
async def test_invalid_request_fails_immediately_without_fallback():
    """Verify 400 INVALID_REQUEST raises immediately and DOES NOT fallback."""
    mock_config = MagicMock()
    p1 = MagicMock(spec=BaseAIProvider)
    p1.name = "groq"
    p1.model = "model-a"
    p1.generate_code = AsyncMock(
        side_effect=ProviderError(ProviderErrorKind.INVALID_REQUEST, "groq", "Bad Request: Malformed JSON", 400)
    )

    p2 = MagicMock(spec=BaseAIProvider)
    p2.name = "gemini"
    p2.model = "model-b"
    p2.generate_code = AsyncMock(return_value="code")

    engine = AISolverEngine(config=mock_config, providers=[p1, p2])
    req = make_dummy_request()

    # Must raise ProviderError directly without trying p2
    with pytest.raises(ProviderError, match="INVALID_REQUEST"):
        await engine.solve(req)

    p1.generate_code.assert_called_once()
    p2.generate_code.assert_not_called()


@pytest.mark.asyncio
async def test_all_providers_failing_raises_solver_error():
    """Verify engine raises SolverError when all providers in chain fail."""
    mock_config = MagicMock()
    p1 = MagicMock(spec=BaseAIProvider)
    p1.name = "groq"
    p1.model = "model-a"
    p1.generate_code = AsyncMock(
        side_effect=ProviderError(ProviderErrorKind.UNAVAILABLE, "groq", "Server 503", 503)
    )

    p2 = MagicMock(spec=BaseAIProvider)
    p2.name = "gemini"
    p2.model = "model-b"
    p2.generate_code = AsyncMock(
        side_effect=ProviderError(ProviderErrorKind.UNAVAILABLE, "gemini", "Server 500", 500)
    )

    engine = AISolverEngine(config=mock_config, providers=[p1, p2])
    req = make_dummy_request()

    with pytest.raises(SolverError, match="All AI providers exhausted"):
        await engine.solve(req)


def test_unconfigured_model_raises_config_error(monkeypatch, temp_dir):
    """Verify engine fails loudly with ConfigError when API key is set but model ID is absent.

    Correct semantics:
    - No API key → silently skip (provider not configured)
    - API key present + no model → ConfigError (misconfiguration, fail loudly)
    """
    config_file = temp_dir / "config.yaml"
    config_file.write_text("solver:\n  fallback_chain: ['groq']\n", encoding="utf-8")

    # Ensure GROQ_MODEL is not set (missing model ID)
    monkeypatch.delenv("GROQ_MODEL", raising=False)
    # Set GROQ_API_KEY so the provider is "configured" and model absence is flagged
    monkeypatch.setenv("GROQ_API_KEY", "gsk_test_key_for_unit_test")

    cm = ConfigManager(config_file=str(config_file), load_env_file=False)

    with pytest.raises(ConfigError, match="Missing required model ID"):
        AISolverEngine(config=cm)
