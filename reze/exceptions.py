"""
Custom exceptions hierarchy for Reze.
"""

class RezeException(Exception):
    """Base exception for all Reze errors."""
    pass

class ConfigurationError(RezeException):
    """Raised when critical configuration settings are missing or invalid."""
    pass

class SecurityError(RezeException):
    """Raised when an unauthorized action or privilege escalation is attempted."""
    pass

class TelegramAPIError(RezeException):
    """Raised when a Telegram API call fails."""
    pass

class FloodWaitError(TelegramAPIError):
    """Raised when Telegram requests rate-limit cooldown."""
    def __init__(self, seconds: int):
        self.seconds = seconds
        super().__init__(f"Telegram FloodWait: Required to wait {seconds} seconds.")

class PluginError(RezeException):
    """Raised during plugin loading, validation, or execution."""
    pass

class CommandExecutionError(RezeException):
    """Raised when command syntax or arguments are invalid."""
    pass
