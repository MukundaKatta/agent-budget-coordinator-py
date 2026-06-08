"""agent-budget-coordinator-py — compose multiple budget caps for agent calls."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable


class BudgetExceeded(Exception):
    """Raised when any budget cap is exceeded."""

    def __init__(self, budget_name: str, reason: str) -> None:
        self.budget_name = budget_name
        self.reason = reason
        super().__init__(f"Budget '{budget_name}' exceeded: {reason}")


@dataclass
class Budget:
    """Base class for a single budget constraint."""

    name: str

    def check(self, **kwargs: Any) -> None:
        """Raise BudgetExceeded if the budget is exhausted. Called before each LLM call."""
        raise NotImplementedError

    def record(self, **kwargs: Any) -> None:
        """Update budget state after a call completes."""
        pass

    def reset(self) -> None:
        """Reset this budget's state."""
        pass


@dataclass
class TokenBudget(Budget):
    """Cap on total input+output tokens."""

    max_tokens: int
    _used: int = field(default=0, init=False, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)

    def check(self, estimated_tokens: int = 0, **_: Any) -> None:
        with self._lock:
            if self._used + estimated_tokens > self.max_tokens:
                raise BudgetExceeded(
                    self.name,
                    f"Would use {self._used + estimated_tokens} tokens (max {self.max_tokens})",
                )

    def record(self, tokens_used: int = 0, **_: Any) -> None:
        with self._lock:
            self._used += tokens_used

    def reset(self) -> None:
        with self._lock:
            self._used = 0

    @property
    def remaining(self) -> int:
        return max(0, self.max_tokens - self._used)

    @property
    def used(self) -> int:
        return self._used


@dataclass
class CostBudget(Budget):
    """Cap on total USD cost."""

    max_usd: float
    _spent: float = field(default=0.0, init=False, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)

    def check(self, estimated_cost: float = 0.0, **_: Any) -> None:
        with self._lock:
            if self._spent + estimated_cost > self.max_usd:
                raise BudgetExceeded(
                    self.name,
                    f"Would spend ${self._spent + estimated_cost:.4f} (max ${self.max_usd:.4f})",
                )

    def record(self, cost: float = 0.0, **_: Any) -> None:
        with self._lock:
            self._spent += cost

    def reset(self) -> None:
        with self._lock:
            self._spent = 0.0

    @property
    def remaining_usd(self) -> float:
        return max(0.0, self.max_usd - self._spent)

    @property
    def spent(self) -> float:
        return self._spent


@dataclass
class CallCountBudget(Budget):
    """Cap on the number of LLM API calls."""

    max_calls: int
    _count: int = field(default=0, init=False, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)

    def check(self, **_: Any) -> None:
        with self._lock:
            if self._count >= self.max_calls:
                raise BudgetExceeded(
                    self.name,
                    f"Call limit reached ({self.max_calls} calls)",
                )

    def record(self, **_: Any) -> None:
        with self._lock:
            self._count += 1

    def reset(self) -> None:
        with self._lock:
            self._count = 0

    @property
    def remaining(self) -> int:
        return max(0, self.max_calls - self._count)

    @property
    def count(self) -> int:
        return self._count


@dataclass
class TimeBudget(Budget):
    """Cap on total wall-clock time (seconds)."""

    max_seconds: float
    _start: float = field(default_factory=time.monotonic, init=False, repr=False)

    def check(self, **_: Any) -> None:
        elapsed = time.monotonic() - self._start
        if elapsed > self.max_seconds:
            raise BudgetExceeded(
                self.name,
                f"Time limit exceeded ({elapsed:.1f}s > {self.max_seconds}s)",
            )

    def reset(self) -> None:
        self._start = time.monotonic()

    @property
    def elapsed(self) -> float:
        return time.monotonic() - self._start

    @property
    def remaining_seconds(self) -> float:
        return max(0.0, self.max_seconds - self.elapsed)


class BudgetCoordinator:
    """
    Compose multiple budget constraints for agent calls.

    Checks all budgets before each call and records consumption after.

    Example::

        coordinator = BudgetCoordinator()
        coordinator.add(TokenBudget("tokens", max_tokens=100_000))
        coordinator.add(CostBudget("cost", max_usd=1.00))
        coordinator.add(CallCountBudget("calls", max_calls=50))

        # Before each LLM call:
        coordinator.check(estimated_tokens=1000, estimated_cost=0.01)

        # After the call completes:
        coordinator.record(tokens_used=850, cost=0.0085)

        # Or wrap a function:
        @coordinator.wrap(estimate_fn=lambda msgs: {"estimated_tokens": 500})
        def call_llm(messages):
            return client.chat(messages)
    """

    def __init__(self) -> None:
        self._budgets: list[Budget] = []

    def add(self, budget: Budget) -> "BudgetCoordinator":
        """Add a budget constraint."""
        self._budgets.append(budget)
        return self

    def check(self, **kwargs: Any) -> None:
        """Check all budgets. Raises BudgetExceeded on the first failure."""
        for budget in self._budgets:
            budget.check(**kwargs)

    def record(self, **kwargs: Any) -> None:
        """Record consumption across all budgets."""
        for budget in self._budgets:
            budget.record(**kwargs)

    def reset(self) -> None:
        """Reset all budgets."""
        for budget in self._budgets:
            budget.reset()

    def wrap(
        self,
        estimate_fn: Callable[..., dict] | None = None,
        record_fn: Callable[..., dict] | None = None,
    ) -> Callable[[Callable], Callable]:
        """
        Decorator that checks budgets before a call and records consumption after.

        ``estimate_fn`` is invoked with the wrapped function's own arguments and
        should return a dict of ``check`` keyword arguments (e.g.
        ``{"estimated_tokens": 500}``). ``record_fn`` is invoked with the same
        arguments plus the keyword ``result`` holding the return value, and should
        return a dict of ``record`` keyword arguments (e.g. ``{"tokens_used": 480}``).

        Both ``estimate_fn`` and ``record_fn`` receive the original positional and
        keyword arguments exactly as the wrapped function was called, so they work
        whether arguments are passed positionally or by keyword.

        Args:
            estimate_fn: Called as ``estimate_fn(*args, **kwargs)`` → dict for ``check``.
            record_fn: Called as ``record_fn(*args, result=result, **kwargs)`` → dict for ``record``.

        Returns:
            A decorator that wraps the target callable.
        """
        import functools

        def decorator(fn: Callable) -> Callable:
            @functools.wraps(fn)
            def wrapper(*args: Any, **kwargs: Any) -> Any:
                estimates = estimate_fn(*args, **kwargs) if estimate_fn else {}
                self.check(**estimates)
                result = fn(*args, **kwargs)
                actuals = (
                    record_fn(*args, result=result, **kwargs) if record_fn else {}
                )
                self.record(**actuals)
                return result

            return wrapper

        return decorator

    def summary(self) -> dict:
        """Return a summary of all budget states."""
        out: dict[str, Any] = {}
        for budget in self._budgets:
            info: dict[str, Any] = {"name": budget.name}
            if isinstance(budget, TokenBudget):
                info.update({"used": budget.used, "max": budget.max_tokens,
                              "remaining": budget.remaining})
            elif isinstance(budget, CostBudget):
                info.update({"spent": budget.spent, "max_usd": budget.max_usd,
                              "remaining_usd": budget.remaining_usd})
            elif isinstance(budget, CallCountBudget):
                info.update({"count": budget.count, "max": budget.max_calls,
                              "remaining": budget.remaining})
            elif isinstance(budget, TimeBudget):
                info.update({"elapsed": budget.elapsed,
                              "max_seconds": budget.max_seconds,
                              "remaining_seconds": budget.remaining_seconds})
            out[budget.name] = info
        return out


__all__ = [
    "BudgetCoordinator",
    "BudgetExceeded",
    "Budget",
    "TokenBudget",
    "CostBudget",
    "CallCountBudget",
    "TimeBudget",
]
