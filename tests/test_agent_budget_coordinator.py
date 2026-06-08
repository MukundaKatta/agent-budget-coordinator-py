"""Tests for agent-budget-coordinator-py."""

import time
import pytest
from agent_budget_coordinator import (
    BudgetCoordinator,
    BudgetExceeded,
    TokenBudget,
    CostBudget,
    CallCountBudget,
    TimeBudget,
)


# TokenBudget tests


def test_token_budget_allows_within_limit():
    b = TokenBudget("tokens", max_tokens=1000)
    b.check(estimated_tokens=500)


def test_token_budget_raises_on_exceed():
    b = TokenBudget("tokens", max_tokens=100)
    b.record(tokens_used=80)
    with pytest.raises(BudgetExceeded) as exc_info:
        b.check(estimated_tokens=30)
    assert exc_info.value.budget_name == "tokens"


def test_token_budget_remaining():
    b = TokenBudget("tokens", max_tokens=1000)
    b.record(tokens_used=300)
    assert b.remaining == 700
    assert b.used == 300


def test_token_budget_reset():
    b = TokenBudget("tokens", max_tokens=100)
    b.record(tokens_used=90)
    b.reset()
    assert b.used == 0
    assert b.remaining == 100


# CostBudget tests


def test_cost_budget_allows():
    b = CostBudget("cost", max_usd=1.00)
    b.check(estimated_cost=0.50)


def test_cost_budget_raises():
    b = CostBudget("cost", max_usd=0.10)
    b.record(cost=0.08)
    with pytest.raises(BudgetExceeded):
        b.check(estimated_cost=0.05)


def test_cost_budget_remaining():
    b = CostBudget("cost", max_usd=1.00)
    b.record(cost=0.30)
    assert abs(b.remaining_usd - 0.70) < 1e-9
    assert abs(b.spent - 0.30) < 1e-9


def test_cost_budget_reset():
    b = CostBudget("cost", max_usd=1.00)
    b.record(cost=0.50)
    b.reset()
    assert b.spent == 0.0


# CallCountBudget tests


def test_call_count_budget_allows():
    b = CallCountBudget("calls", max_calls=5)
    b.check()
    b.record()
    assert b.count == 1


def test_call_count_budget_raises():
    b = CallCountBudget("calls", max_calls=2)
    b.record()
    b.record()
    with pytest.raises(BudgetExceeded) as exc_info:
        b.check()
    assert "calls" in exc_info.value.budget_name


def test_call_count_budget_remaining():
    b = CallCountBudget("calls", max_calls=5)
    b.record()
    b.record()
    assert b.remaining == 3
    assert b.count == 2


def test_call_count_budget_reset():
    b = CallCountBudget("calls", max_calls=3)
    b.record()
    b.reset()
    assert b.count == 0


# TimeBudget tests


def test_time_budget_allows():
    b = TimeBudget("time", max_seconds=60.0)
    b.check()


def test_time_budget_elapsed():
    b = TimeBudget("time", max_seconds=60.0)
    time.sleep(0.05)
    assert b.elapsed >= 0.05


def test_time_budget_remaining():
    b = TimeBudget("time", max_seconds=10.0)
    assert b.remaining_seconds <= 10.0


# BudgetCoordinator tests


def test_coordinator_all_pass():
    coord = BudgetCoordinator()
    coord.add(TokenBudget("tokens", max_tokens=1000))
    coord.add(CostBudget("cost", max_usd=1.00))
    coord.check(estimated_tokens=100, estimated_cost=0.01)


def test_coordinator_raises_on_first_failure():
    coord = BudgetCoordinator()
    coord.add(TokenBudget("tokens", max_tokens=10))
    coord.add(CostBudget("cost", max_usd=1.00))
    with pytest.raises(BudgetExceeded) as exc_info:
        coord.check(estimated_tokens=100, estimated_cost=0.01)
    assert exc_info.value.budget_name == "tokens"


def test_coordinator_record_all():
    coord = BudgetCoordinator()
    tb = TokenBudget("tokens", max_tokens=1000)
    cb = CostBudget("cost", max_usd=1.00)
    coord.add(tb).add(cb)
    coord.record(tokens_used=100, cost=0.05)
    assert tb.used == 100
    assert abs(cb.spent - 0.05) < 1e-9


def test_coordinator_reset_all():
    coord = BudgetCoordinator()
    tb = TokenBudget("tokens", max_tokens=100)
    coord.add(tb)
    coord.record(tokens_used=80)
    coord.reset()
    assert tb.used == 0


def test_coordinator_summary():
    coord = BudgetCoordinator()
    coord.add(TokenBudget("tokens", max_tokens=1000))
    coord.add(CallCountBudget("calls", max_calls=10))
    summary = coord.summary()
    assert "tokens" in summary
    assert "calls" in summary
    assert summary["tokens"]["max"] == 1000


def test_coordinator_wrap():
    coord = BudgetCoordinator()
    calls_b = CallCountBudget("calls", max_calls=3)
    coord.add(calls_b)

    call_count = []

    @coord.wrap()
    def call_llm(messages):
        call_count.append(1)
        return "response"

    call_llm("msg1")
    call_llm("msg2")
    call_llm("msg3")
    assert len(call_count) == 3
    with pytest.raises(BudgetExceeded):
        call_llm("msg4")


def test_budget_exceeded_error():
    exc = BudgetExceeded("my_budget", "too much")
    assert exc.budget_name == "my_budget"
    assert exc.reason == "too much"
    assert "my_budget" in str(exc)


def test_coordinator_chaining():
    coord = BudgetCoordinator()
    result = coord.add(TokenBudget("t", max_tokens=100))
    assert result is coord


def test_coordinator_summary_time_budget():
    coord = BudgetCoordinator()
    coord.add(TimeBudget("time", max_seconds=42.0))
    summary = coord.summary()
    assert summary["time"]["max_seconds"] == 42.0
    assert "elapsed" in summary["time"]
    assert "remaining_seconds" in summary["time"]


def test_wrap_estimate_and_record_fns_receive_kwargs():
    coord = BudgetCoordinator()
    tb = TokenBudget("tokens", max_tokens=10_000)
    coord.add(tb)

    seen = {}

    def estimate_fn(*args, **kwargs):
        seen["estimate"] = (args, kwargs)
        return {"estimated_tokens": kwargs.get("estimated_tokens", 0)}

    def record_fn(*args, **kwargs):
        # args == (*call_args, result); kwargs are the call's keyword args
        seen["record"] = (args, kwargs)
        return {"tokens_used": kwargs.get("estimated_tokens", 0)}

    @coord.wrap(estimate_fn=estimate_fn, record_fn=record_fn)
    def call_llm(messages, estimated_tokens=0):
        return "response"

    result = call_llm("hi", estimated_tokens=250)
    assert result == "response"
    # estimate_fn received the keyword argument
    assert seen["estimate"][1] == {"estimated_tokens": 250}
    # record_fn received the original kwargs (regression: these were dropped before)
    assert seen["record"][1] == {"estimated_tokens": 250}
    # record_fn received the result as the trailing positional arg
    assert seen["record"][0] == ("hi", "response")
    # the consumption was actually recorded
    assert tb.used == 250


def test_wrap_without_fns_still_runs():
    coord = BudgetCoordinator()
    coord.add(CallCountBudget("calls", max_calls=2))

    @coord.wrap()
    def call_llm(messages):
        return messages.upper()

    assert call_llm("a") == "A"
    assert call_llm("b") == "B"
    with pytest.raises(BudgetExceeded):
        call_llm("c")
