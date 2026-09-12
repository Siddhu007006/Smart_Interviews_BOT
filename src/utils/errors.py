"""
Custom exceptions for the Hive Automation Bot.
"""


class HiveBotError(Exception):
    """Base exception for all HiveBot errors"""
    pass


class AuthenticationError(HiveBotError):
    """Authentication or session-related error"""
    pass


class DOMError(HiveBotError):
    """DOM query or inspection error"""
    pass


class ProblemExtractionError(DOMError):
    """Problem detail extraction error"""
    pass



class EditorError(HiveBotError):
    """Code editor interaction error"""
    pass


class SolverError(HiveBotError):
    """AI solver pipeline error"""
    pass


class VerdictError(HiveBotError):
    """Verdict parsing error"""
    pass


class SubmissionError(HiveBotError):
    """Submission execution error or safety guard violation"""
    pass


class StateError(HiveBotError):
    """State management or persistence error"""
    pass


class NetworkError(HiveBotError):
    """Network connectivity error"""
    pass


class TimeoutError(HiveBotError):
    """Operation timeout error"""
    pass


class ConfigError(HiveBotError):
    """Configuration loading or validation error"""
    pass


class ExtensionError(HiveBotError):
    """Browser extension verification error"""
    pass


class BrowserError(HiveBotError):
    """Browser management error"""
    pass
