# agent-budget-coordinator-py

Compose multiple budget caps — token, cost, call count, and wall-clock time —
for agent LLM calls. Check every budget *before* a call and record actual
consumption *after*, so a single agent never blows past its limits.

The library is dependency-free, fully type-hinted, and the per-call counters
(`TokenBudget`, `CostBudget`, `CallCountBudget`) are guarded by locks, so a
coordinator can be shared across threads.

## Install

```bash
pip install agent-budget-coordinator-py
```

## Usage

```python
from agent_budget_coordinator import (
    BudgetCoordinator, TokenBudget, CostBudget, CallCountBudget, TimeBudget,
    BudgetExceeded,
)

coord = BudgetCoordinator()
coord.add(TokenBudget("tokens", max_tokens=100_000))
coord.add(CostBudget("cost", max_usd=1.00))
coord.add(CallCountBudget("calls", max_calls=50))
coord.add(TimeBudget("time", max_seconds=300.0))

try:
    # Before the call: pass estimates. Raises BudgetExceeded if any cap would break.
    coord.check(estimated_tokens=1000, estimated_cost=0.01)

    response = call_llm(messages)

    # After the call: record what was actually consumed.
    coord.record(tokens_used=850, cost=0.0085)
except BudgetExceeded as e:
    print(f"Budget '{e.budget_name}' exceeded: {e.reason}")

print(coord.summary())  # per-budget usage stats
coord.reset()           # zero every counter and restart the time clock
```

`CallCountBudget` and `TimeBudget` need no estimates — the count is incremented
on `record()` and the elapsed time is measured from when the budget was created
(or last `reset()`).

### Wrapping a function

`BudgetCoordinator.wrap()` returns a decorator that runs `check()` before the
call and `record()` after it. Supply `estimate_fn` and `record_fn` to translate
your function's arguments and return value into budget keyword arguments:

```python
@coord.wrap(
    estimate_fn=lambda messages: {"estimated_tokens": estimate_tokens(messages)},
    record_fn=lambda messages, result: {
        "tokens_used": result.usage.total_tokens,
        "cost": price(result),
    },
)
def call_llm(messages):
    return client.chat(messages)
```

- `estimate_fn` is called with the wrapped function's own arguments and returns
  a dict passed to `check()`.
- `record_fn` is called with the same arguments plus the keyword `result`
  (the return value) and returns a dict passed to `record()`. Because the
  original arguments are forwarded by both position and keyword, the callbacks
  work whether you call the wrapped function positionally or with keywords.

If the budget check fails, `BudgetExceeded` propagates and the wrapped function
is never invoked, so nothing is recorded for the rejected call.

## API

| Object | Constructor | Notes |
| --- | --- | --- |
| `TokenBudget(name, max_tokens)` | caps input+output tokens | `check(estimated_tokens=…)`, `record(tokens_used=…)`, props `used`, `remaining` |
| `CostBudget(name, max_usd)` | caps total USD | `check(estimated_cost=…)`, `record(cost=…)`, props `spent`, `remaining_usd` |
| `CallCountBudget(name, max_calls)` | caps number of calls | `record()` increments, props `count`, `remaining` |
| `TimeBudget(name, max_seconds)` | caps wall-clock seconds | props `elapsed`, `remaining_seconds`; `reset()` restarts the clock |
| `BudgetCoordinator()` | groups budgets | `add()`, `check()`, `record()`, `reset()`, `wrap()`, `summary()` |
| `BudgetExceeded` | raised on any breach | attributes `budget_name`, `reason` |

`check()` evaluates budgets in insertion order and raises on the first breach.
`Budget` is the base class if you want to add a custom constraint — override
`check()` (and optionally `record()` / `reset()`).

## Development

Run the test suite with the standard library only (no third-party deps):

```bash
python3 -m unittest discover -s tests
```

## License

MIT
