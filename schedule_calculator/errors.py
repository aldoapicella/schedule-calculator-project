from __future__ import annotations


class ScheduleCalculatorError(Exception):
    """Base exception for production-facing failures."""


class ConfigurationError(ScheduleCalculatorError):
    """Raised when runtime configuration is missing or invalid."""


class ValidationError(ScheduleCalculatorError):
    """Raised when user input or scraped data is invalid."""


class PortalParseError(ScheduleCalculatorError):
    """Raised when the portal HTML does not match expected structure."""


class PortalRequestError(ScheduleCalculatorError):
    """Raised when the portal cannot be reached reliably."""


class PersistenceError(ScheduleCalculatorError):
    """Raised when database operations fail."""
