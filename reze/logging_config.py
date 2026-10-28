"""
Centralized logging configuration for Reze Userbot.
Includes sensitive data sanitization and log record buffer for web panel.
"""

import logging
import re
from collections import deque
from typing import List, Dict

# In-memory circular buffer for fast web UI display (latest 500 lines)
LOG_BUFFER: deque = deque(maxlen=500)

SENSITIVE_PATTERNS = [
    re.compile(r"(api_hash=['\"]?)[a-f0-9]{32}(['\"]?)", re.IGNORECASE),
    re.compile(r"(password_hash=['\"]?)[^'\"]+(['\"])", re.IGNORECASE),
    re.compile(r"(session=['\"]?)[^'\"]+(['\"])", re.IGNORECASE),
    re.compile(r"(secret[_-]?key=['\"]?)[^'\"]+(['\"])", re.IGNORECASE),
    re.compile(r"(api[_-]?key['\"]?\s*[:=]\s*['\"]?)[A-Za-z0-9_\-]{8,}", re.IGNORECASE),
    re.compile(r"(Bearer\s+)[A-Za-z0-9._\-]{8,}", re.IGNORECASE),
    re.compile(r"(?<![:/\d])\b\d{5}\b(?![\d:])"),  # mask Telegram login codes (not ports/paths)
]


class SensitiveDataFilter(logging.Filter):
    """Masks credentials, bearer tokens and auth codes before they are stored."""

    def filter(self, record: logging.LogRecord) -> bool:
        msg = str(record.getMessage())
        for pattern in SENSITIVE_PATTERNS:
            msg = pattern.sub(
                r"\1***MASKED***\2" if pattern.groups >= 2 else "***MASKED_CODE***", msg
            )
        record.msg = msg
        record.args = ()
        return True


class BufferLogHandler(logging.Handler):
    """Stores formatted records in memory for the dashboard log view."""

    def emit(self, record: logging.LogRecord):
        try:
            LOG_BUFFER.append(
                {
                    "created": record.created,
                    "timestamp": self.format(record),
                    "level": record.levelname,
                    "module": record.name,
                    "message": self.format(record),
                }
            )
        except Exception:
            pass


def setup_logging(log_level: str = "INFO") -> logging.Logger:
    """Set up root logger with formatters, filters, console & buffer handlers."""
    logger = logging.getLogger("reze")
    logger.setLevel(getattr(logging, log_level.upper(), logging.INFO))
    
    if not logger.handlers:
        formatter = logging.Formatter(
            fmt="[%(asctime)s] [%(levelname)s] [%(name)s]: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        )
        
        # Console Handler
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        console_handler.addFilter(SensitiveDataFilter())
        logger.addHandler(console_handler)
        
        # Buffer Handler for Web Dashboard
        buffer_handler = BufferLogHandler()
        buffer_handler.setFormatter(formatter)
        buffer_handler.addFilter(SensitiveDataFilter())
        logger.addHandler(buffer_handler)
        
    return logger


logger = setup_logging()
