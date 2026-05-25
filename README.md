# agent-budget-coordinator-py

Compose multiple budget caps (token, cost, call count, time) for agent LLM calls. Check all budgets before each call and record consumption after.

## Install

```bash
pip install agent-budget-coordinator-py
```

## Usage

```python
from agent_budget_coordinator import (
    BudgetCoordinator, TokenBudget, CostBudget, CallCountBudget, TimeBudget, BudgetExceeded
)

coord = BudgetCoordinator()
coord.add(TokenBudget("tokens", max_tokens=100_000))
coord.add(CostBudget("cost", max_usd=1.00))
coord.add(CallCountBudget("calls", max_calls=50))
coord.add(TimeBudget("time", max_seconds=300.0))

try:
    coord.check(estimated_tokens=1000, estimated_cost=0.01)
    response = call_llm(messages)
    coord.record(tokens_used=850, cost=0.0085)
except BudgetExceeded as e:
    print(f"Budget '{e.budget_name}' exceeded: {e.reason}")

# Or wrap a function
@coord.wrap()
def call_llm(messages):
    return client.chat(messages)

print(coord.summary())  # per-budget usage stats
coord.reset()
```

## License

MIT
