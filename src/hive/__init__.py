"""
Hive platform interaction module.

Exports:
- DOMInspector: Safe DOM query utilities
- ProblemListDetector: Problem list detection and navigation
- Problem: Problem metadata dataclass
"""

from .dom_queries import DOMInspector
from .problem_list import ProblemListDetector, Problem

__all__ = ["DOMInspector", "ProblemListDetector", "Problem"]
