"""Exception types raised by QueryDoctor."""

from __future__ import annotations


class QueryDoctorError(Exception):
    """Base class for all expected, user-facing errors."""


class UnsafeSQLError(QueryDoctorError):
    """Raised when supplied SQL is not a single read-only SELECT statement."""


class DatabaseNotFoundError(QueryDoctorError):
    """Raised when the target database file does not exist."""


class QueryTimeoutError(QueryDoctorError):
    """Raised when a measured query exceeds the configured time limit."""
