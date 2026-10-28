"""
Exception hierarchy for Reze.

Every error that reaches a user is rendered through the ASCII engine, so the
messages here are short, actionable and free of secrets.
"""


class RezeException(Exception):
    """Base exception for all Reze errors."""


class ConfigurationError(RezeException):
    """Raised when critical configuration settings are missing or invalid."""


class SecurityError(RezeException):
    """Raised when an unauthorized action or privilege escalation is attempted."""


class TelegramAPIError(RezeException):
    """Raised when a Telegram API call fails."""


class FloodWaitError(TelegramAPIError):
    """Raised when Telegram requests a rate-limit cooldown."""

    def __init__(self, seconds: int):
        self.seconds = seconds
        super().__init__(f"Telegram FloodWait: required to wait {seconds} seconds.")


class PluginError(RezeException):
    """Raised during plugin loading, validation, or execution."""


class ManifestError(PluginError):
    """Raised when a plugin manifest is missing, malformed or incompatible."""


class DuplicateCommandError(PluginError):
    """Raised when two plugins (or a plugin and a built-in) claim one command."""


class CommandExecutionError(RezeException):
    """Raised when command syntax or arguments are invalid."""


class ConfirmationError(SecurityError):
    """Raised when a confirmation token is invalid, expired or already used."""


class TaskError(RezeException):
    """Base class for background task failures."""


class TaskQueueFull(TaskError):
    """Raised when the bounded task queue is saturated."""


class TaskNotFound(TaskError):
    """Raised when a task identifier is unknown or already evicted."""


class MediaError(RezeException):
    """Raised when media validation or conversion fails."""


class MissingDependencyError(MediaError):
    """Raised when an optional tool (Pillow, FFmpeg, ...) is unavailable."""


class AIError(RezeException):
    """Base class for AI gateway failures."""


class AIConfigurationError(AIError):
    """Raised when no provider is configured or credentials are missing."""


class AIProviderError(AIError):
    """Raised when a provider returns an error or an unusable response."""


class AIRateLimitError(AIProviderError):
    """Raised when a provider rate limit or quota is exhausted."""


class AITimeoutError(AIProviderError):
    """Raised when a provider request exceeds the configured timeout."""
