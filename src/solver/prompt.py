"""
Prompt builder for competitive programming code generation and iterative repair.
"""

from typing import Dict, Any
from src.solver.models import SolutionRequest


class PromptBuilder:
    """Builds optimal competitive programming prompts for initial generation and error repair."""

    @staticmethod
    def build_prompt(request: SolutionRequest) -> str:
        """Construct the prompt from problem specification and any previous failure context."""
        parts = []

        # System / context instruction
        parts.append(
            f"You are an expert competitive programmer. Write a complete, optimal, and correct solution in {request.language} "
            f"that solves the following problem under all given constraints."
        )
        parts.append("\n--- PROBLEM DETAILS ---")
        parts.append(f"Title: {request.title}")
        parts.append(f"\nDescription:\n{request.description}")

        if request.input_format:
            parts.append(f"\nInput Format:\n{request.input_format}")

        if request.output_format:
            parts.append(f"\nOutput Format:\n{request.output_format}")

        if request.constraints:
            parts.append(f"\nConstraints:\n{request.constraints}")

        if request.sample_cases:
            parts.append("\nSample Cases:")
            for idx, sc in enumerate(request.sample_cases, start=1):
                parts.append(f"Sample #{idx}:")
                parts.append(f"Input:\n{sc.input_data}")
                parts.append(f"Output:\n{sc.output_data}")
                if sc.explanation:
                    parts.append(f"Explanation: {sc.explanation}")

        # Iterative repair instructions if prior attempt failed
        if request.attempt_number > 1 and request.previous_code:
            parts.append("\n--- REPAIR INSTRUCTIONS (PREVIOUS ATTEMPT FAILED) ---")
            parts.append(f"Attempt: #{request.attempt_number}")
            if request.previous_verdict:
                parts.append(f"Previous Verdict: {request.previous_verdict}")
            if request.previous_error:
                parts.append(f"Failure / Diagnostic Details:\n{request.previous_error}")
            parts.append(f"\nPrevious Code that Failed:\n```{request.language}\n{request.previous_code}\n```")
            parts.append(
                "Identify the exact reason for the failure (e.g. integer overflow, TLE, 1-off indexing, edge cases, I/O format) "
                "and provide a completely corrected solution."
            )

        # Output format constraints
        parts.append("\n--- CODING REQUIREMENTS ---")
        parts.append(f"1. Provide a COMPLETE, standalone, and runnable {request.language} program.")
        parts.append("2. Read input from standard input (stdin) and print output to standard output (stdout).")
        parts.append("3. Use fast I/O where appropriate.")
        parts.append("4. IMPORTANT: Do NOT include any conversational introduction, explanations, or analysis.")
        parts.append("5. Output ONLY the code inside standard markdown fences (``` ... ```) or as pure code.")
        parts.append("6. Match the EXACT output format and casing specified in Output Format and Sample Cases (e.g., lowercase 'true'/'false' vs uppercase 'YES'/'NO').")
        parts.append("7. Ensure strict mathematical correctness and handle edge cases (e.g., target sum = 0, negative numbers, minimum constraints, distinct partition boundaries).")

        return "\n".join(parts)
