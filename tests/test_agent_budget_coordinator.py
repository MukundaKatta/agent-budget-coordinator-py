"""Tests for agent-budget-coordinator-py.

These tests use only the Python standard library (``unittest``) so they run
without any third-party dependencies::

    python3 -m unittest discover -s tests
"""

import os
import sys
import time
import unittest

# Make ``src`` importable when tests are run from the repository root without an
# editable install (e.g. ``python3 -m unittest discover -s tests``).
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from agent_budget_coordinator import (  # noqa: E402
    Budget,
    BudgetCoordinator,
    BudgetExceeded,
    CallCountBudget,
    CostBudget,
    TimeBudget,
    TokenBudget,
)


class TokenBudgetTests(unittest.TestCase):
    def test_allows_within_limit(self):
        b = TokenBudget("tokens", max_tokens=1000)
        b.check(estimated_tokens=500)  # should not raise

    def test_raises_on_exceed(self):
        b = TokenBudget("tokens", max_tokens=100)
        b.record(tokens_used=80)
        with self.assertRaises(BudgetExceeded) as ctx:
            b.check(estimated_tokens=30)
        self.assertEqual(ctx.exception.budget_name, "tokens")

    def test_exact_limit_is_allowed(self):
        b = TokenBudget("tokens", max_tokens=100)
        b.record(tokens_used=70)
        b.check(estimated_tokens=30)  # 70 + 30 == 100, not over

    def test_remaining_and_used(self):
        b = TokenBudget("tokens", max_tokens=1000)
        b.record(tokens_used=300)
        self.assertEqual(b.remaining, 700)
        self.assertEqual(b.used, 300)

    def test_remaining_never_negative(self):
        b = TokenBudget("tokens", max_tokens=100)
        b.record(tokens_used=150)
        self.assertEqual(b.remaining, 0)

    def test_reset(self):
        b = TokenBudget("tokens", max_tokens=100)
        b.record(tokens_used=90)
        b.reset()
        self.assertEqual(b.used, 0)
        self.assertEqual(b.remaining, 100)


class CostBudgetTests(unittest.TestCase):
    def test_allows(self):
        b = CostBudget("cost", max_usd=1.00)
        b.check(estimated_cost=0.50)

    def test_raises(self):
        b = CostBudget("cost", max_usd=0.10)
        b.record(cost=0.08)
        with self.assertRaises(BudgetExceeded):
            b.check(estimated_cost=0.05)

    def test_remaining_and_spent(self):
        b = CostBudget("cost", max_usd=1.00)
        b.record(cost=0.30)
        self.assertAlmostEqual(b.remaining_usd, 0.70)
        self.assertAlmostEqual(b.spent, 0.30)

    def test_reset(self):
        b = CostBudget("cost", max_usd=1.00)
        b.record(cost=0.50)
        b.reset()
        self.assertEqual(b.spent, 0.0)


class CallCountBudgetTests(unittest.TestCase):
    def test_allows_and_records(self):
        b = CallCountBudget("calls", max_calls=5)
        b.check()
        b.record()
        self.assertEqual(b.count, 1)

    def test_raises_when_full(self):
        b = CallCountBudget("calls", max_calls=2)
        b.record()
        b.record()
        with self.assertRaises(BudgetExceeded) as ctx:
            b.check()
        self.assertIn("calls", ctx.exception.budget_name)

    def test_remaining(self):
        b = CallCountBudget("calls", max_calls=5)
        b.record()
        b.record()
        self.assertEqual(b.remaining, 3)
        self.assertEqual(b.count, 2)

    def test_reset(self):
        b = CallCountBudget("calls", max_calls=3)
        b.record()
        b.reset()
        self.assertEqual(b.count, 0)


class TimeBudgetTests(unittest.TestCase):
    def test_allows(self):
        b = TimeBudget("time", max_seconds=60.0)
        b.check()

    def test_elapsed_advances(self):
        b = TimeBudget("time", max_seconds=60.0)
        time.sleep(0.05)
        self.assertGreaterEqual(b.elapsed, 0.05)

    def test_remaining_within_bounds(self):
        b = TimeBudget("time", max_seconds=10.0)
        self.assertLessEqual(b.remaining_seconds, 10.0)
        self.assertGreaterEqual(b.remaining_seconds, 0.0)

    def test_raises_when_exceeded(self):
        b = TimeBudget("time", max_seconds=0.0)
        time.sleep(0.01)
        with self.assertRaises(BudgetExceeded):
            b.check()

    def test_reset_restarts_clock(self):
        b = TimeBudget("time", max_seconds=10.0)
        time.sleep(0.05)
        before = b.elapsed
        b.reset()
        self.assertLess(b.elapsed, before)


class BudgetBaseTests(unittest.TestCase):
    def test_base_check_not_implemented(self):
        b = Budget("base")
        with self.assertRaises(NotImplementedError):
            b.check()

    def test_base_record_and_reset_are_noops(self):
        b = Budget("base")
        b.record()  # should not raise
        b.reset()  # should not raise


class BudgetCoordinatorTests(unittest.TestCase):
    def test_all_pass(self):
        coord = BudgetCoordinator()
        coord.add(TokenBudget("tokens", max_tokens=1000))
        coord.add(CostBudget("cost", max_usd=1.00))
        coord.check(estimated_tokens=100, estimated_cost=0.01)

    def test_raises_on_first_failure(self):
        coord = BudgetCoordinator()
        coord.add(TokenBudget("tokens", max_tokens=10))
        coord.add(CostBudget("cost", max_usd=1.00))
        with self.assertRaises(BudgetExceeded) as ctx:
            coord.check(estimated_tokens=100, estimated_cost=0.01)
        self.assertEqual(ctx.exception.budget_name, "tokens")

    def test_record_all(self):
        coord = BudgetCoordinator()
        tb = TokenBudget("tokens", max_tokens=1000)
        cb = CostBudget("cost", max_usd=1.00)
        coord.add(tb).add(cb)
        coord.record(tokens_used=100, cost=0.05)
        self.assertEqual(tb.used, 100)
        self.assertAlmostEqual(cb.spent, 0.05)

    def test_reset_all(self):
        coord = BudgetCoordinator()
        tb = TokenBudget("tokens", max_tokens=100)
        coord.add(tb)
        coord.record(tokens_used=80)
        coord.reset()
        self.assertEqual(tb.used, 0)

    def test_summary(self):
        coord = BudgetCoordinator()
        coord.add(TokenBudget("tokens", max_tokens=1000))
        coord.add(CallCountBudget("calls", max_calls=10))
        summary = coord.summary()
        self.assertIn("tokens", summary)
        self.assertIn("calls", summary)
        self.assertEqual(summary["tokens"]["max"], 1000)

    def test_summary_includes_all_budget_types(self):
        coord = BudgetCoordinator()
        coord.add(TokenBudget("tokens", max_tokens=1000))
        coord.add(CostBudget("cost", max_usd=2.0))
        coord.add(CallCountBudget("calls", max_calls=10))
        coord.add(TimeBudget("time", max_seconds=30.0))
        summary = coord.summary()
        self.assertEqual(summary["cost"]["max_usd"], 2.0)
        self.assertEqual(summary["calls"]["max"], 10)
        # max_seconds is exposed for TimeBudget so the cap is discoverable.
        self.assertEqual(summary["time"]["max_seconds"], 30.0)

    def test_add_returns_self_for_chaining(self):
        coord = BudgetCoordinator()
        result = coord.add(TokenBudget("t", max_tokens=100))
        self.assertIs(result, coord)

    def test_empty_coordinator_check_and_record(self):
        coord = BudgetCoordinator()
        coord.check(estimated_tokens=999999)  # no budgets -> never raises
        coord.record(tokens_used=999999)


class WrapTests(unittest.TestCase):
    def test_wrap_counts_calls_and_raises_when_exhausted(self):
        coord = BudgetCoordinator()
        coord.add(CallCountBudget("calls", max_calls=3))
        calls = []

        @coord.wrap()
        def call_llm(messages):
            calls.append(messages)
            return "response"

        call_llm("msg1")
        call_llm("msg2")
        call_llm("msg3")
        self.assertEqual(len(calls), 3)
        with self.assertRaises(BudgetExceeded):
            call_llm("msg4")

    def test_wrap_uses_estimate_and_record_fns(self):
        coord = BudgetCoordinator()
        tb = TokenBudget("tokens", max_tokens=1000)
        coord.add(tb)

        @coord.wrap(
            estimate_fn=lambda messages: {"estimated_tokens": 100},
            record_fn=lambda messages, result: {"tokens_used": len(result)},
        )
        def call_llm(messages):
            return "abcd"

        out = call_llm("hello")
        self.assertEqual(out, "abcd")
        self.assertEqual(tb.used, 4)

    def test_wrap_record_fn_receives_args_with_keyword_calls(self):
        # Regression test: previously record_fn lost the original call arguments
        # when the wrapped function was invoked with keyword arguments.
        coord = BudgetCoordinator()
        seen = {}

        # record_fn mirrors the wrapped function's signature plus ``result``.
        def record_fn(messages, model="gpt", result=None):
            seen["messages"] = messages
            seen["model"] = model
            seen["result"] = result
            return {}

        @coord.wrap(record_fn=record_fn)
        def call_llm(messages, model="gpt"):
            return "resp"

        call_llm(messages="hi", model="gpt-4")
        self.assertEqual(seen["messages"], "hi")
        self.assertEqual(seen["model"], "gpt-4")
        self.assertEqual(seen["result"], "resp")

    def test_wrap_preserves_function_metadata(self):
        coord = BudgetCoordinator()

        @coord.wrap()
        def documented(messages):
            """A documented function."""
            return messages

        self.assertEqual(documented.__name__, "documented")
        self.assertEqual(documented.__doc__, "A documented function.")

    def test_wrap_does_not_record_when_check_fails(self):
        coord = BudgetCoordinator()
        calls = CallCountBudget("calls", max_calls=1)
        coord.add(calls)

        @coord.wrap()
        def call_llm(messages):
            return "ok"

        call_llm("first")
        self.assertEqual(calls.count, 1)
        with self.assertRaises(BudgetExceeded):
            call_llm("second")
        # The rejected call must not have been recorded.
        self.assertEqual(calls.count, 1)


class BudgetExceededTests(unittest.TestCase):
    def test_attributes_and_message(self):
        exc = BudgetExceeded("my_budget", "too much")
        self.assertEqual(exc.budget_name, "my_budget")
        self.assertEqual(exc.reason, "too much")
        self.assertIn("my_budget", str(exc))
        self.assertIn("too much", str(exc))

    def test_is_an_exception(self):
        self.assertTrue(issubclass(BudgetExceeded, Exception))


if __name__ == "__main__":
    unittest.main()
