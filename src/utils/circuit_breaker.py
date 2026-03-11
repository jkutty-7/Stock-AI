"""In-memory circuit breaker for external API calls (Groww, Anthropic).

States:
  CLOSED  — normal operation, calls pass through
  OPEN    — too many failures, calls blocked for reset_seconds
  HALF_OPEN — one trial call allowed after reset window passes

Usage:
    cb = CircuitBreaker(threshold=5, reset_seconds=60, name="groww")
    if cb.is_open():
        raise GrowwAPIError("Circuit open — Groww API temporarily disabled")
    try:
        result = await some_api_call()
        cb.record_success()
    except Exception:
        cb.record_failure()
        raise
"""

import logging
import time

logger = logging.getLogger(__name__)

_CLOSED = "CLOSED"
_OPEN = "OPEN"
_HALF_OPEN = "HALF_OPEN"


class CircuitBreaker:
    """Simple in-memory circuit breaker."""

    def __init__(
        self,
        threshold: int = 5,
        reset_seconds: float = 60.0,
        name: str = "api",
    ) -> None:
        self.threshold = threshold
        self.reset_seconds = reset_seconds
        self.name = name
        self._state = _CLOSED
        self._failure_count = 0
        self._opened_at: float = 0.0

    # ----------------------------------------------------------------
    # Public API
    # ----------------------------------------------------------------

    def is_open(self) -> bool:
        """Return True if the circuit is OPEN (calls should be blocked)."""
        self._maybe_transition_to_half_open()
        return self._state == _OPEN

    def record_success(self) -> None:
        """Record a successful call — resets failure counter."""
        if self._state == _HALF_OPEN:
            logger.info(f"[CircuitBreaker:{self.name}] Recovered — closing circuit")
        self._state = _CLOSED
        self._failure_count = 0

    def record_failure(self) -> None:
        """Record a failed call — may trip the circuit to OPEN."""
        self._failure_count += 1
        if self._state == _HALF_OPEN:
            # Trial call failed — re-open
            self._open_circuit()
        elif self._failure_count >= self.threshold:
            self._open_circuit()

    @property
    def state(self) -> str:
        self._maybe_transition_to_half_open()
        return self._state

    @property
    def failure_count(self) -> int:
        return self._failure_count

    # ----------------------------------------------------------------
    # Internal
    # ----------------------------------------------------------------

    def _open_circuit(self) -> None:
        self._state = _OPEN
        self._opened_at = time.monotonic()
        logger.warning(
            f"[CircuitBreaker:{self.name}] OPEN after {self._failure_count} failures. "
            f"Blocking calls for {self.reset_seconds}s"
        )

    def _maybe_transition_to_half_open(self) -> None:
        if self._state == _OPEN:
            elapsed = time.monotonic() - self._opened_at
            if elapsed >= self.reset_seconds:
                self._state = _HALF_OPEN
                logger.info(
                    f"[CircuitBreaker:{self.name}] HALF-OPEN — allowing trial call"
                )
