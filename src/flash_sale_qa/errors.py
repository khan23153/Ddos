from __future__ import annotations

from typing import Any


class QaHarnessError(RuntimeError):
    """Base exception for expected harness failures."""


class ConfigurationError(QaHarnessError):
    """Raised when configuration is invalid or unsafe."""


class ApiError(QaHarnessError):
    """Raised when the staging API returns an unexpected response."""

    def __init__(self, message: str, status: int | None = None, body: Any = None) -> None:
        super().__init__(message)
        self.status = status
        self.body = body


class StopAccount(QaHarnessError):
    """Raised when an account should not be retried for the current blitz."""
