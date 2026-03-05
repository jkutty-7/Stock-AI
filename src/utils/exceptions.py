"""Custom exception hierarchy for Stock AI."""


class StockAIError(Exception):
    """Base exception for all Stock AI errors."""


class GrowwAPIError(StockAIError):
    """Groww API call failures — authentication, rate limits, timeouts."""

    def __init__(self, message: str, status_code: int | None = None):
        self.status_code = status_code
        super().__init__(message)


class GrowwAuthError(GrowwAPIError):
    """Groww authentication failure — token expired or invalid credentials."""


class GrowwRateLimitError(GrowwAPIError):
    """Groww API rate limit exceeded."""

    def __init__(self, message: str = "Rate limit exceeded", retry_after: float | None = None):
        self.retry_after = retry_after
        super().__init__(message)


class AIAnalysisError(StockAIError):
    """Claude API failures or unparseable responses."""


class DatabaseError(StockAIError):
    """MongoDB connection or query failures."""


class MarketDataError(StockAIError):
    """Market data fetch or computation failures."""


class TelegramError(StockAIError):
    """Telegram bot communication failures."""
