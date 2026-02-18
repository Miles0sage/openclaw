# OpenClaw Cost Gates - Budget Enforcement System

## Overview

Cost Gates is a comprehensive budget enforcement system for OpenClaw that protects against unexpected AI API costs through intelligent tiered budget limits, real-time cost tracking, and D1 database persistence.

**Status:** ✅ Production Ready | **Tests:** 31/31 Passing | **Coverage:** All 3-tier gates

## Features

### 1. Three-Tier Budget Limits

Enforces spending limits at three critical levels:

| Tier         | Default Limit | Warning Threshold | Purpose                             |
| ------------ | ------------- | ----------------- | ----------------------------------- |
| **Per-Task** | $10.00        | $8.00 (80%)       | Prevent expensive single operations |
| **Daily**    | $50.00        | $40.00 (80%)      | Limit daily burn rate               |
| **Monthly**  | $1,000.00     | $800.00 (80%)     | Control monthly spend               |

### 2. Real-Time Cost Calculation

Supports all major models with accurate Feb 2026 pricing:

```python
# Kimi Models (Deepseek)
"kimi-2.5":       $0.27/M input,  $1.10/M output  (95% cheaper than Claude)
"kimi-reasoner":  $0.55/M input,  $2.19/M output  (82% cheaper than Opus)

# Claude Models
"claude-opus-4-6":  $15.0/M input,  $60.0/M output
"claude-3-5-sonnet": $3.0/M input,  $15.0/M output
"claude-3-5-haiku":  $0.8/M input,   $4.0/M output
```

### 3. Budget Status Levels

Every request returns one of three statuses:

- **✅ APPROVED**: Task passes all checks, can execute
- **⚠️ WARNING**: Approaching limits (>80% of tier), alerts sent
- **❌ REJECTED**: Exceeds limit, returns 402 Insufficient Budget

### 4. Persistent Storage

Uses SQLite D1 database with schema for:

- `daily_spending` - Track daily totals by project/agent
- `monthly_spending` - Track monthly totals
- `task_spending` - Detailed task records with token counts
- `budget_approval` - Track approval requests for high-cost tasks

## Usage

### Basic Setup

```python
from cost_gates import get_cost_gates

# Initialize (auto-creates DB at /tmp/openclaw_budget.db)
gates = get_cost_gates()

# Check budget before executing task
result = gates.check_budget(
    project="barber_crm",
    agent="pm",
    model="kimi-2.5",
    tokens_input=1_000_000,
    tokens_output=500_000,
    task_id="booking_analysis_1"
)

if result.status == BudgetStatus.APPROVED:
    # Execute task
    response = execute_llm_call(...)

    # Record actual spending
    gates.record_spending("barber_crm", "pm", result.projected_total)

elif result.status == BudgetStatus.WARNING:
    # Alert user, suggest cheaper model
    logger.warning(f"⚠️  {result.message}")

else:  # REJECTED
    # Return 402 to client
    raise HTTPException(status_code=402, detail=result.message)
```

### Check Result Structure

```python
@dataclass
class CostCheckResult:
    status: BudgetStatus              # APPROVED | WARNING | REJECTED
    remaining_budget: float           # Budget left in current tier
    projected_total: float            # Cost of this task
    message: str                      # Human-readable explanation
    gate_name: str                    # Which gate triggered: "per-task", "daily", "monthly", "warning", "all"
```

### Custom Budget Configuration

```python
config = {
    "per_task": {"limit": 20.0, "threshold_warning": 16.0},
    "daily": {"limit": 100.0, "threshold_warning": 80.0},
    "monthly": {"limit": 2000.0, "threshold_warning": 1600.0},
}

gates = CostGates(config=config, db_path="/path/to/budget.db")
```

### Get Budget Status

```python
status = gates.get_budget_status(project="barber_crm")

# Returns:
{
    "date": "2026-02-18",
    "daily": {
        "spent": 15.50,
        "limit": 50.00,
        "remaining": 34.50,
        "percent_used": 31.0,
    },
    "month": {
        "spent": 234.80,
        "limit": 1000.00,
        "remaining": 765.20,
        "percent_used": 23.5,
    },
}
```

## Integration with Gateway

Add to `/root/openclaw/gateway.py`:

```python
from cost_gates import get_cost_gates, BudgetStatus, init_cost_gates

# At startup
@app.on_event("startup")
async def startup():
    init_cost_gates()  # Initialize global instance

# In /api/chat endpoint
@app.post("/api/chat")
async def chat(request: ChatRequest):
    gates = get_cost_gates()

    # Estimate token usage (or use actual from model)
    tokens_input = len(request.messages) * 100  # rough estimate
    tokens_output = 500  # expected completion tokens

    # Check budget
    budget_check = gates.check_budget(
        project="openclaw",
        agent=request.agent_id,
        model=request.model,
        tokens_input=tokens_input,
        tokens_output=tokens_output,
        task_id=request.task_id
    )

    if budget_check.status == BudgetStatus.REJECTED:
        return JSONResponse(
            status_code=402,
            content={"error": budget_check.message}
        )

    if budget_check.status == BudgetStatus.WARNING:
        logger.warning(f"⚠️  Budget warning: {budget_check.message}")

    # Execute LLM call
    response = anthropic_client.messages.create(...)

    # Record actual spending
    actual_cost = gates.calculate_cost(
        request.model,
        response.usage.input_tokens,
        response.usage.output_tokens
    )
    gates.record_spending("openclaw", request.agent_id, actual_cost)

    return response
```

## Test Coverage

### Test Suite: 31 Tests Passing ✅

```
✅ Pricing Constants (3 tests)
   - Kimi 2.5 pricing verified
   - Kimi Reasoner pricing verified
   - Claude Opus pricing verified

✅ Cost Calculation (4 tests)
   - Kimi 2.5 cost calculation
   - Kimi Reasoner cost calculation
   - Claude Opus cost calculation
   - Low token count edge case

✅ Budget Gates (2 tests)
   - Default gates configuration
   - Custom gates configuration

✅ Per-Task Budget (3 tests)
   - Under limit: APPROVED
   - Exceed limit: REJECTED
   - Near limit: WARNING

✅ Daily Budget (3 tests)
   - First task approved
   - Accumulate spending
   - Exceed limit: REJECTED

✅ Monthly Budget (4 tests)
   - First task of month
   - Accumulate across days
   - Exceed limit: REJECTED
   - Budget status tracking

✅ Database Operations (4 tests)
   - Record/retrieve daily spending
   - Record/retrieve monthly spending
   - Task spending records
   - Approval workflow

✅ Budget Status (2 tests)
   - Status with zero spending
   - Status with recorded spending

✅ Integration Scenarios (3 tests)
   - Small task passes all checks
   - Multiple agents in same project
   - Realistic multi-task workflow

✅ Error Handling (3 tests)
   - Unknown model defaults to Sonnet
   - Zero token cost
   - Negative spending prevention
```

### Run Tests

```bash
# Run all tests
pytest /root/openclaw/test_cost_gates.py -v

# Run specific test class
pytest /root/openclaw/test_cost_gates.py::TestPerTaskBudget -v

# Run with coverage
pytest /root/openclaw/test_cost_gates.py --cov=cost_gates --cov-report=html
```

## Cost Scenarios

### Example 1: Small Booking Query (APPROVED)

```python
result = gates.check_budget(
    project="barber_crm",
    agent="pm",
    model="kimi-2.5",
    tokens_input=10_000,      # Small context
    tokens_output=5_000,      # Small response
    task_id="booking_query_1"
)
# Cost: $0.0027 + $0.0055 = $0.0082
# Status: ✅ APPROVED
```

### Example 2: Complex Analysis (WARNING)

```python
result = gates.check_budget(
    project="barber_crm",
    agent="pm",
    model="kimi-reasoner",
    tokens_input=8_000_000,    # Large analysis
    tokens_output=2_000_000,   # Detailed output
    task_id="complex_analysis"
)
# Cost: $4.40 + $4.38 = $8.78 (80% of $10 task limit)
# Status: ⚠️ WARNING
# Message: "Task cost $8.7800 approaching limits (daily: $8.7800/$50.0, monthly: $8.7800/$1000.0)"
```

### Example 3: Over Daily Budget (REJECTED)

```python
# Already spent $45 today
gates.db.record_daily_spending("barber_crm", "pm", 45.0)

result = gates.check_budget(
    project="barber_crm",
    agent="pm",
    model="kimi-reasoner",
    tokens_input=15_000_000,
    tokens_output=500_000,
    task_id="exceed_daily"
)
# Cost: $8.25 + $1.09 = $9.34
# Total daily: $45 + $9.34 = $54.34 > $50 limit
# Status: ❌ REJECTED
# Message: "Daily spending would reach $54.34, exceeds limit $50.0"
```

## Real-World Performance

### Token Cost Breakdown

Using Kimi 2.5 (95% cheaper than Claude Sonnet):

| Scenario        | Input Tokens | Output Tokens |  Cost  | Savings vs Sonnet |
| --------------- | :----------: | :-----------: | :----: | :---------------: |
| Simple query    |     10K      |      5K       | $0.008 |       -95%        |
| Medium analysis |     100K     |      50K      | $0.082 |       -95%        |
| Complex task    |      1M      |     500K      | $0.82  |       -95%        |
| Large project   |     10M      |      5M       | $8.20  |       -95%        |

### Budget Runway

With $50/day budget using Kimi 2.5:

- **Small tasks** (~$0.01 each): 5,000 tasks/day
- **Medium tasks** (~$0.1 each): 500 tasks/day
- **Large tasks** (~$1 each): 50 tasks/day
- **Complex tasks** (~$10 each): 5 tasks/day

## API Response Codes

| Status   | HTTP Code | Meaning                                    |
| -------- | :-------: | ------------------------------------------ |
| Approved |    200    | Execute task normally                      |
| Warning  |    200    | Execute with logging, suggest optimization |
| Rejected |    402    | "Insufficient Budget" - request blocked    |

## Monitoring & Alerts

### Log Examples

```
INFO: Cost check passed for booking_query_1: $0.0082 cost
⚠️  Budget warning: Task cost $8.7800 approaching limits (daily: $8.7800/$50.0, monthly: $8.7800/$1000.0)
❌ REJECTED: Daily spending would reach $54.34, exceeds limit $50.0
```

### Prometheus Metrics (Future)

```
openclaw_budget_used_daily{project="barber_crm"} 15.5
openclaw_budget_used_monthly{project="barber_crm"} 234.8
openclaw_budget_remaining_daily{project="barber_crm"} 34.5
openclaw_budget_remaining_monthly{project="barber_crm"} 765.2
openclaw_budget_rejections_total 3
```

## Files

| File                                 | Lines | Purpose                          |
| ------------------------------------ | :---: | -------------------------------- |
| `/root/openclaw/cost_gates.py`       |  477  | Main module - budget enforcement |
| `/root/openclaw/test_cost_gates.py`  |  391  | 31 comprehensive tests           |
| `/root/openclaw/COST_GATES_GUIDE.md` | This  | Documentation                    |

## Future Enhancements

- [ ] Cloudflare D1 native integration (currently SQLite compatible)
- [ ] Per-agent spending limits
- [ ] Cost prediction for complex queries
- [ ] Automatic model downgrade (Opus → Sonnet → Haiku)
- [ ] Slack/Discord alerts for budget breaches
- [ ] Cost anomaly detection (spike detection)
- [ ] Budget carryover and monthly rollover policies

## Troubleshooting

### Tests failing with utcnow() deprecation?

Python 3.13 deprecates `utcnow()`. Safe to ignore in tests. Use `datetime.now(datetime.UTC)` in production code if needed.

### Database locked errors?

Ensure only one gateway process is writing to the database. Use a connection pool or centralized logging service for multi-instance deployments.

### Why is my task getting rejected?

1. Check which gate triggered: `result.gate_name`
2. Review current budget: `gates.get_budget_status()`
3. Consider using cheaper model (Kimi vs Claude)
4. Split large tasks into smaller ones
5. Request approval if it's high-value

## Support

For issues, questions, or feature requests:

- See `/root/openclaw/AGENTS.md` for agent architecture
- Check gateway integration in `/root/openclaw/gateway.py`
- Review cost tracker module: `/root/openclaw/cost_tracker.py`

---

**Last Updated:** 2026-02-18 | **Version:** 1.0.0 | **Status:** Production Ready
