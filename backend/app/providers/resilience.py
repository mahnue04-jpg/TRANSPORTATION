"""
Provider Resilience System — circuit breakers, retry budgets, health scoring.

Usage:
    from app.providers.resilience import CircuitBreaker, resilient_call

    breaker = CircuitBreaker("tavily", failure_threshold=3, recovery_timeout=30)

    result = resilient_call(
        providers=[
            ("tavily",    breaker_tavily,    call_tavily),
            ("ddg",       breaker_ddg,       call_ddg),
        ],
        *args, **kwargs
    )

States:
    CLOSED    — Normal operation. Failures accumulate.
    OPEN      — Provider is tripped; calls rejected immediately.
    HALF_OPEN — One probe allowed after recovery_timeout seconds.
"""
from __future__ import annotations

import logging
import time
from collections import deque
from threading import Lock
from typing import Any, Callable

from app import logging_utils

logger = logging.getLogger("amicor.resilience")


# ── Circuit breaker states ─────────────────────────────────────────────────────

CLOSED    = "closed"
OPEN      = "open"
HALF_OPEN = "half_open"


class CircuitBreaker:
    """
    Thread-safe circuit breaker for a single provider.

    Args:
        name:               Human-readable provider name.
        failure_threshold:  Consecutive failures before OPEN (default 3).
        recovery_timeout:   Seconds before attempting HALF_OPEN probe (default 30).
        success_threshold:  Successes in HALF_OPEN before returning to CLOSED (default 1).
        window_size:        Rolling window for health score calculation (default 20).
        timeout_seconds:    Per-call timeout injected as context (informational, not enforced here).
    """

    def __init__(
        self,
        name: str,
        failure_threshold: int = 3,
        recovery_timeout:  int = 30,
        success_threshold: int = 1,
        window_size:       int = 20,
        timeout_seconds:   int = 10,
    ) -> None:
        self.name              = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout  = recovery_timeout
        self.success_threshold = success_threshold
        self.timeout_seconds   = timeout_seconds

        self._state         = CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._last_failure  = 0.0
        self._lock          = Lock()

        # Rolling window: True = success, False = failure
        self._window: deque[bool] = deque(maxlen=window_size)

    # ── State queries ──────────────────────────────────────────────────────────

    @property
    def state(self) -> str:
        with self._lock:
            return self._state

    @property
    def health_score(self) -> float:
        """0.0 (fully broken) – 1.0 (fully healthy)."""
        with self._lock:
            if not self._window:
                return 1.0
            return sum(self._window) / len(self._window)

    def is_available(self) -> bool:
        """Returns True if a call should be attempted."""
        with self._lock:
            if self._state == CLOSED:
                return True
            if self._state == OPEN:
                elapsed = time.monotonic() - self._last_failure
                if elapsed >= self.recovery_timeout:
                    logging_utils.log_event(
                        logger,
                        logging.INFO,
                        event="provider.breaker.state_change",
                        message="Provider circuit state changed",
                        provider=self.name,
                        from_state=OPEN,
                        to_state=HALF_OPEN,
                        elapsed_s=round(elapsed, 1),
                    )
                    self._state = HALF_OPEN
                    self._success_count = 0
                    return True
                return False
            # HALF_OPEN — allow one probe
            return True

    # ── Outcome recording ──────────────────────────────────────────────────────

    def record_success(self) -> None:
        with self._lock:
            self._window.append(True)
            self._failure_count = 0
            if self._state == HALF_OPEN:
                self._success_count += 1
                if self._success_count >= self.success_threshold:
                    logging_utils.log_event(
                        logger,
                        logging.INFO,
                        event="provider.breaker.state_change",
                        message="Provider circuit state changed",
                        provider=self.name,
                        from_state=HALF_OPEN,
                        to_state=CLOSED,
                    )
                    self._state = CLOSED

    def record_failure(self) -> None:
        with self._lock:
            self._window.append(False)
            self._last_failure = time.monotonic()
            self._failure_count += 1
            if self._state in (CLOSED, HALF_OPEN):
                if self._failure_count >= self.failure_threshold:
                    logging_utils.log_event(
                        logger,
                        logging.WARNING,
                        event="provider.breaker.state_change",
                        message="Provider circuit state changed",
                        provider=self.name,
                        from_state=self._state,
                        to_state=OPEN,
                        failure_count=self._failure_count,
                    )
                    self._state = OPEN

    # ── Diagnostics ───────────────────────────────────────────────────────────

    def diagnostics(self) -> dict:
        with self._lock:
            return {
                "name":           self.name,
                "state":          self._state,
                "health_score":   round(self.health_score, 3),
                "failure_count":  self._failure_count,
                "window_calls":   len(self._window),
                "window_success": sum(self._window),
                "last_failure_s": round(time.monotonic() - self._last_failure, 1) if self._last_failure else None,
            }


# ── Retry budget ───────────────────────────────────────────────────────────────

class RetryBudget:
    """
    Limits total retries across an operation (not per-provider).
    Used to prevent cascade amplification.
    """

    def __init__(self, max_retries: int = 2, base_delay: float = 0.25) -> None:
        self.max_retries = max_retries
        self.base_delay  = base_delay
        self._used       = 0

    def can_retry(self) -> bool:
        return self._used < self.max_retries

    def consume(self) -> float:
        """Consume one retry slot; return the delay to wait before next attempt."""
        delay = self.base_delay * (2 ** self._used)
        self._used += 1
        return delay

    def reset(self) -> None:
        self._used = 0


# ── resilient_call ─────────────────────────────────────────────────────────────

def resilient_call(
    providers: list[tuple[str, CircuitBreaker, Callable]],
    *args: Any,
    retry_budget: RetryBudget | None = None,
    **kwargs: Any,
) -> tuple[Any, str]:
    """
    Call providers in priority order, honouring circuit breakers.

    Args:
        providers:     List of (name, breaker, callable) tuples ordered by preference.
        *args/**kwargs: Forwarded verbatim to each callable.
        retry_budget:  Optional shared retry budget.

    Returns:
        (result, provider_name) on success.

    Raises:
        RuntimeError if all providers fail / are OPEN.
    """
    budget = retry_budget or RetryBudget(max_retries=1)
    errors: list[str] = []

    for name, breaker, fn in providers:
        if not breaker.is_available():
            logging_utils.log_event(
                logger,
                logging.DEBUG,
                event="provider.call.skipped",
                message="Provider call skipped",
                provider=name,
                reason="circuit_open",
            )
            errors.append(f"{name}: circuit open")
            continue

        attempt = 0
        while True:
            try:
                result = fn(*args, **kwargs)
                breaker.record_success()
                logging_utils.log_event(
                    logger,
                    logging.DEBUG,
                    event="provider.call.success",
                    message="Provider call succeeded",
                    provider=name,
                    attempt=attempt + 1,
                    state=breaker.state,
                )
                return result, name
            except Exception as exc:
                breaker.record_failure()
                err_msg = f"{name} attempt {attempt + 1}: {exc}"
                logging_utils.log_event(
                    logger,
                    logging.WARNING,
                    event="provider.call.error",
                    message="Provider call failed",
                    provider=name,
                    attempt=attempt + 1,
                    state=breaker.state,
                    error=logging_utils.safe_exception_message(exc),
                )
                errors.append(err_msg)

                if budget.can_retry():
                    delay = budget.consume()
                    time.sleep(delay)
                    attempt += 1
                    continue
                break  # exhausted retries for this provider

    raise RuntimeError(
        f"All providers failed or are open. Errors: {'; '.join(errors)}"
    )


# ── Global registry ────────────────────────────────────────────────────────────
# A shared per-process registry so breaker state persists across requests.

_registry: dict[str, CircuitBreaker] = {}
_registry_lock = Lock()


def get_breaker(
    name: str,
    failure_threshold: int = 3,
    recovery_timeout:  int = 30,
) -> CircuitBreaker:
    """Get or create a named circuit breaker (singleton per process)."""
    with _registry_lock:
        if name not in _registry:
            _registry[name] = CircuitBreaker(
                name,
                failure_threshold=failure_threshold,
                recovery_timeout=recovery_timeout,
            )
        return _registry[name]


def all_diagnostics() -> list[dict]:
    """Return diagnostics for every registered circuit breaker."""
    with _registry_lock:
        return [cb.diagnostics() for cb in _registry.values()]
