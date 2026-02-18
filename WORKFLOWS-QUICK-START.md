# Workflow Engine - Quick Start Guide

## Installation

The Workflow Engine is already built into OpenClaw. Just import and use:

```python
from workflow_engine import WorkflowExecutor, WorkflowManager, create_website_build_workflow
import asyncio

# Initialize
executor = WorkflowExecutor()
manager = WorkflowManager()
```

## Execute Built-in Workflow

```python
async def main():
    # Load a workflow
    workflow = manager.load_workflow("website-build-001")

    # Execute
    execution = await executor.execute_workflow(workflow)

    # Check status
    print(f"Status: {execution.status}")
    print(f"Duration: {execution.duration_seconds}s")
    print(f"Cost: ${execution.total_cost_usd:.2f}")

    # View logs
    logs = executor.get_execution_logs(execution.execution_id)
    print(logs)

asyncio.run(main())
```

## Available Workflows

1. **Website Build Pipeline** (`website-build-001`)
   - CodeGen builds frontend
   - Security audits code
   - Deploy to production

2. **Code Review Pipeline** (`code-review-001`)
   - CodeGen implements feature
   - Security reviews and approves

3. **Documentation Pipeline** (`documentation-001`)
   - CodeGen writes code
   - PM creates documentation

## Create Custom Workflow

```python
from workflow_engine import WorkflowDefinition, TaskDefinition, TaskType

tasks = [
    TaskDefinition(
        id="task1",
        name="Build Component",
        type=TaskType.AGENT_CALL,
        agent_id="coder_agent",
        prompt="Build a reusable React component",
    ),
    TaskDefinition(
        id="task2",
        name="Test Component",
        type=TaskType.AGENT_CALL,
        agent_id="coder_agent",
        prompt="Write comprehensive tests",
    ),
]

workflow = WorkflowDefinition(
    id="custom-component-001",
    name="Build & Test Component",
    tasks=tasks,
)

manager.save_workflow(workflow)
execution = await executor.execute_workflow(workflow)
```

## Task Types

### Agent Call

```python
TaskDefinition(
    id="build",
    type=TaskType.AGENT_CALL,
    agent_id="coder_agent",  # or "hacker_agent" or "project_manager"
    prompt="Your instructions here",
)
```

### HTTP Request

```python
TaskDefinition(
    id="deploy",
    type=TaskType.HTTP_REQUEST,
    url="https://api.example.com/deploy",
    method="POST",
)
```

### Conditional Branching

```python
TaskDefinition(
    id="check",
    type=TaskType.CONDITIONAL,
    condition="status == 'success'",
)
```

### Parallel Tasks

```python
TaskDefinition(
    id="tests",
    type=TaskType.PARALLEL,
    parallel_tasks=[
        TaskDefinition(...),  # Unit tests
        TaskDefinition(...),  # Integration tests
    ],
)
```

## Error Handling

### Retries with Backoff

```python
TaskDefinition(
    id="task",
    type=TaskType.AGENT_CALL,
    agent_id="coder_agent",
    prompt="...",
    retry_count=3,          # Try 3 times
    retry_backoff=2.0,      # Exponential: 1s, 2s, 4s
)
```

### Skip on Error

```python
TaskDefinition(
    id="optional",
    type=TaskType.AGENT_CALL,
    agent_id="coder_agent",
    prompt="...",
    skip_on_error=True,     # Don't fail workflow if this fails
)
```

## Monitoring

### Get Status

```python
status = executor.get_execution_status(execution_id)
print(status['status'])  # 'running', 'completed', 'failed', etc.
```

### Get Logs

```python
logs = executor.get_execution_logs(execution_id)
print(logs)
```

### Cancel Execution

```python
executor.cancel_execution(execution_id)
```

## Testing

```bash
# Run all tests
pytest test_workflows.py -v

# Run specific test
pytest test_workflows.py::TestWorkflowExecutor::test_execute_simple_workflow -v

# With coverage
pytest test_workflows.py --cov=workflow_engine
```

## Key Classes

| Class                | Purpose                          |
| -------------------- | -------------------------------- |
| `WorkflowExecutor`   | Executes workflows, tracks state |
| `WorkflowManager`    | Saves/loads workflow definitions |
| `WorkflowDefinition` | Workflow blueprint               |
| `TaskDefinition`     | Individual task spec             |
| `WorkflowExecution`  | Execution record with status     |
| `TaskExecution`      | Individual task execution result |

## File Structure

```
/root/openclaw/
├── workflow_engine.py              # Engine (883 LOC)
├── test_workflows.py               # Tests (630 LOC, 31 tests)
├── WORKFLOWS.md                    # Full documentation
├── WORKFLOWS-QUICK-START.md        # This file
└── /tmp/openclaw_workflows/
    ├── definitions/                # Saved workflow definitions
    ├── executions/                 # Execution records
    └── logs/                       # Execution logs
```

## Deployment

Add to `gateway.py`:

```python
from workflow_engine import WorkflowExecutor, WorkflowManager

executor = WorkflowExecutor(agent_router=agent_router, cost_tracker=log_cost_event)
manager = WorkflowManager()

@app.post("/api/workflows/execute")
async def execute_workflow(request: dict):
    workflow = manager.load_workflow(request["workflow_id"])
    execution = await executor.execute_workflow(workflow, request.get("context"))
    return execution.to_dict()

@app.get("/api/workflows/{execution_id}/status")
async def get_status(execution_id: str):
    return executor.get_execution_status(execution_id)

@app.get("/api/workflows/{execution_id}/logs")
async def get_logs(execution_id: str):
    return {"logs": executor.get_execution_logs(execution_id)}

@app.delete("/api/workflows/{execution_id}")
async def cancel(execution_id: str):
    success = executor.cancel_execution(execution_id)
    return {"cancelled": success}
```

## Examples

### Run Website in Parallel

```python
import asyncio

workflows = [
    manager.load_workflow("website-build-001"),
    manager.load_workflow("website-build-001"),
    manager.load_workflow("website-build-001"),
]

executions = await asyncio.gather(*[
    executor.execute_workflow(w) for w in workflows
])

print(f"Completed {len(executions)} workflows")
```

### Complex Workflow

```python
workflow = WorkflowDefinition(
    id="full-pipeline",
    name="Complete CI/CD",
    tasks=[
        TaskDefinition(id="build", type=TaskType.AGENT_CALL, agent_id="coder_agent", prompt="Build app"),
        TaskDefinition(
            id="tests",
            type=TaskType.PARALLEL,
            parallel_tasks=[
                TaskDefinition(id="unit", type=TaskType.AGENT_CALL, agent_id="coder_agent", prompt="Unit tests"),
                TaskDefinition(id="e2e", type=TaskType.AGENT_CALL, agent_id="coder_agent", prompt="E2E tests"),
                TaskDefinition(id="security", type=TaskType.AGENT_CALL, agent_id="hacker_agent", prompt="Security scan"),
            ],
        ),
        TaskDefinition(id="deploy", type=TaskType.HTTP_REQUEST, url="https://api.vercel.com/deploy", method="POST"),
    ],
)

execution = await executor.execute_workflow(workflow)
```

## Troubleshooting

| Problem        | Solution                                                    |
| -------------- | ----------------------------------------------------------- |
| Workflow hangs | Check logs, set timeout_seconds, verify agent availability  |
| High costs     | Use cheaper models, reduce retries, use intelligent routing |
| Execution lost | Check /tmp/openclaw_workflows/executions/ directory         |
| Task fails     | View execution logs, check task configuration               |

## Documentation

- **Full Docs**: `WORKFLOWS.md` (1043 lines)
- **API Reference**: `WORKFLOWS.md#api-endpoints`
- **Examples**: `WORKFLOWS.md#usage-examples`
- **Troubleshooting**: `WORKFLOWS.md#troubleshooting`

## Support

- Tests: `test_workflows.py` (31 tests, 630 LOC)
- Report issues in logs: `executor.get_execution_logs(execution_id)`
- View workflow definitions: `manager.list_workflows()`
