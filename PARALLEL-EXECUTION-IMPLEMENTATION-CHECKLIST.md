# OpenClaw Parallel Execution - Implementation Checklist

## Pre-Development

### Planning Phase

- [ ] Review PARALLEL-EXECUTION-ARCHITECTURE.md (full document)
- [ ] Review PARALLEL-EXECUTION-QUICK-REFERENCE.md (examples)
- [ ] Understand current flow: gateway.py → agent_router.py → single agent
- [ ] Identify key integration points:
  - [ ] gateway.py line 503 (where routing happens)
  - [ ] agent_router.py (routing decision logic)
  - [ ] cost_tracker.py (logging costs)
  - [ ] orchestrator.py (message routing)
- [ ] Set up development database for testing
  - [ ] Create test sessions directory
  - [ ] Create test cost logs
- [ ] Clone repo to feature branch: `git checkout -b feature/parallel-execution`

### Dependency Audit

- [ ] Verify Python packages installed:
  - [ ] asyncio (built-in)
  - [ ] dataclasses (built-in)
  - [ ] typing (built-in)
  - [ ] anthropic (already have)
  - [ ] fastapi (already have)
  - [ ] pydantic (already have)
- [ ] No new external dependencies needed ✓

---

## Phase 1: Core Components (Week 1)

### 1.1 Create parallel_executor.py (450 LOC)

**Checklist:**

- [ ] Create file: `/root/openclaw/parallel_executor.py`
- [ ] Implement `ParallelExecutorConfig` dataclass
  - [ ] max_tasks_per_execution: int = 6
  - [ ] timeout_per_task_sec: int = 300
  - [ ] pm_decomposition_model: str = "claude-opus-4-6"
  - [ ] enable_conflict_resolution: bool = True
- [ ] Implement `ParallelTask` dataclass
  - [ ] id, pool_type, description, context
  - [ ] status, result, error, timestamps
- [ ] Implement `ParallelExecutionResult` dataclass
  - [ ] execution_id, status, tasks, results
  - [ ] duration_sec, total_cost, quality_score
- [ ] Implement `ParallelExecutor` class
  - [ ] `__init__()` - initialize pools & aggregator
  - [ ] `execute_parallel()` - main orchestration method
  - [ ] `_enqueue_tasks()` - distribute to pools
  - [ ] `_wait_for_completion()` - await all tasks
  - [ ] `_handle_results()` - collect & validate results
  - [ ] Error handling: timeouts, failures, retries
- [ ] Add logging at key points (info/debug level)
- [ ] Type hints on all methods
- [ ] Docstrings for all public methods
- [ ] Handle edge cases:
  - [ ] Empty task list
  - [ ] All tasks fail
  - [ ] Mixed success/failure

**Testing:**

- [ ] Unit test: `test_parallel_executor_init()`
- [ ] Unit test: `test_execute_parallel_basic()`
- [ ] Unit test: `test_handle_timeouts()`
- [ ] Unit test: `test_handle_failures()`

---

### 1.2 Create worker_pools.py (380 LOC)

**Checklist:**

- [ ] Create file: `/root/openclaw/worker_pools.py`
- [ ] Implement `WorkerPool` base class
  - [ ] `__init__()` - max_concurrent, timeout
  - [ ] `enqueue_task()` - add to queue
  - [ ] `get_task()` - pull from queue
  - [ ] `mark_complete()` - task done
  - [ ] `mark_failed()` - task failed
  - [ ] `wait_for_task()` - async wait
  - [ ] Properties: queue_length, active_count
- [ ] Implement `CodeGenWorkerPool(WorkerPool)`
  - [ ] max_concurrent = 3
  - [ ] timeout_sec = 300
  - [ ] Specialized prompt formatting
- [ ] Implement `SecurityWorkerPool(WorkerPool)`
  - [ ] max_concurrent = 2
  - [ ] timeout_sec = 300
  - [ ] Audit-specific prompts
- [ ] Implement `DatabaseWorkerPool(WorkerPool)`
  - [ ] max_concurrent = 2
  - [ ] timeout_sec = 180
  - [ ] Schema/data-specific prompts
- [ ] Task queue management (asyncio.Queue)
- [ ] Concurrency limits enforcement
- [ ] Timeout tracking per task
- [ ] Retry queuing logic
- [ ] Logging for debugging

**Testing:**

- [ ] Unit test: `test_worker_pool_enqueue()`
- [ ] Unit test: `test_worker_pool_concurrency_limit()`
- [ ] Unit test: `test_worker_pool_timeout()`
- [ ] Unit test: `test_worker_pool_retry()`

---

### 1.3 Create task_distributor.py (220 LOC)

**Checklist:**

- [ ] Create file: `/root/openclaw/task_distributor.py`
- [ ] Implement `TaskDistributor` class
  - [ ] CODEGEN_KEYWORDS list
  - [ ] SECURITY_KEYWORDS list
  - [ ] DATABASE_KEYWORDS list
- [ ] Implement `distribute()` method
  - [ ] Keyword matching on task description
  - [ ] Score calculation for each pool type
  - [ ] Return best pool + confidence score
- [ ] Implement `_analyze_intent()` method
  - [ ] NLP-like scoring (keyword count / total words)
  - [ ] Multi-keyword phrase matching
  - [ ] Confidence thresholds
- [ ] Implement fallback logic
  - [ ] If no keywords match → return "multi" (needs PM decision)
  - [ ] If multiple pools score equally → tie-break logic
- [ ] Implement `_create_task()` method
  - [ ] Generate unique task ID
  - [ ] Set defaults (timeout, retries)
  - [ ] Validate inputs

**Testing:**

- [ ] Unit test: `test_distribute_codegen_task()`
- [ ] Unit test: `test_distribute_security_task()`
- [ ] Unit test: `test_distribute_database_task()`
- [ ] Unit test: `test_distribute_multi_agent_task()`

---

### 1.4 Create result_aggregator.py (320 LOC)

**Checklist:**

- [ ] Create file: `/root/openclaw/result_aggregator.py`
- [ ] Implement `ResultAggregator` class
  - [ ] `aggregate()` - main method
  - [ ] `_validate_results()` - check completeness
  - [ ] `_resolve_conflicts()` - handle disagreements
  - [ ] `_detect_dependencies()` - find task relationships
  - [ ] `_build_unified_context()` - merge outputs
  - [ ] `_apply_security_first()` - prioritize security findings
- [ ] Implement conflict detection
  - [ ] CodeGen suggests approach, Security flags risk
  - [ ] Two agents recommend different tools
  - [ ] Contradictory findings
- [ ] Implement conflict resolution
  - [ ] Rule 1: Security recommendations always apply
  - [ ] Rule 2: Merge complementary advice
  - [ ] Rule 3: Flag irreconcilable conflicts for PM
- [ ] Implement dependency tracking
  - [ ] Frontend depends on Backend API → Backend must complete first
  - [ ] Frontend depends on Database schema → Database must complete first
- [ ] Implement `AggregatedResult` dataclass
  - [ ] codegen_output, security_output, database_output
  - [ ] conflicts_detected list
  - [ ] dependencies list
  - [ ] recommendations list
  - [ ] summary string
- [ ] Logging for aggregation process

**Testing:**

- [ ] Unit test: `test_aggregate_successful_results()`
- [ ] Unit test: `test_detect_conflict_csrf()`
- [ ] Unit test: `test_resolve_conflict_security_first()`
- [ ] Unit test: `test_detect_dependency()`
- [ ] Unit test: `test_aggregate_partial_results()`

---

## Phase 2: PM Coordination (Week 2)

### 2.1 Create pm_coordinator.py (380 LOC)

**Checklist:**

- [ ] Create file: `/root/openclaw/pm_coordinator.py`
- [ ] Implement `PMCoordinator` class
  - [ ] `decompose_into_parallel_tasks()` - main method
  - [ ] `coordinate_execution()` - orchestrate execution
  - [ ] `synthesize_final_response()` - generate output
- [ ] Implement `decompose_into_parallel_tasks()`
  - [ ] Call Claude Opus with extended thinking
  - [ ] Prompt: "Break this request into independent parallel tasks"
  - [ ] Parse response to extract task list
  - [ ] Validate each task has pool type and description
  - [ ] Return List[ParallelTask]
- [ ] Implement `coordinate_execution()`
  - [ ] Call parallel_executor.execute_parallel()
  - [ ] Wait for execution to complete
  - [ ] Handle execution errors
  - [ ] Return CoordinationResult
- [ ] Implement `synthesize_final_response()`
  - [ ] Combine all agent outputs
  - [ ] Create client-facing message
  - [ ] Include timeline, cost, next steps
  - [ ] Add PM signature
- [ ] Error handling
  - [ ] PM decomposition fails → fall back to serial
  - [ ] Execution fails → return partial results with error
- [ ] PM persona integration
  - [ ] Use PM's signature on output
  - [ ] Use PM's playful traits in messaging
  - [ ] Include emojis per persona

**Testing:**

- [ ] Unit test: `test_pm_decompose_website_build()`
- [ ] Unit test: `test_pm_decompose_security_audit()`
- [ ] Unit test: `test_pm_synthesize_response()`

---

### 2.2 Create failure_handler.py (280 LOC)

**Checklist:**

- [ ] Create file: `/root/openclaw/failure_handler.py`
- [ ] Implement `FailureHandler` class
  - [ ] `handle_task_failure()` - main entry point
  - [ ] `handle_timeout()` - specific handler
  - [ ] `handle_agent_unavailable()` - specific handler
  - [ ] `handle_agent_error()` - specific handler
- [ ] Implement retry logic
  - [ ] Track retry count per task
  - [ ] Max retries = 2 (configurable)
  - [ ] Exponential backoff: 1s, 3s, 9s
  - [ ] Return FailureResolution after max retries
- [ ] Implement fallback strategies
  - [ ] RETRY: Queue task again
  - [ ] FALLBACK: Use lighter model
  - [ ] ESCALATE: Ask PM for manual intervention
  - [ ] SKIP: Continue without this result
  - [ ] REFUND: Calculate partial refund
- [ ] Implement graceful degradation
  - [ ] If CodeGen times out: return "pending" to client
  - [ ] If Security times out: return unaudited results
  - [ ] If Database times out: return without optimization
- [ ] Logging
  - [ ] Every failure logged with context
  - [ ] Every retry logged with attempt number
  - [ ] Final resolution logged

**Testing:**

- [ ] Unit test: `test_retry_task()`
- [ ] Unit test: `test_timeout_handling()`
- [ ] Unit test: `test_graceful_degradation()`

---

### 2.3 Integration Tests

**File: test_parallel_executor.py (650 LOC)**

**Checklist:**

- [ ] Create file: `/root/openclaw/test_parallel_executor.py`
- [ ] Implement mock agents (for testing)
  - [ ] `MockCodeGenAgent` - returns sample code
  - [ ] `MockSecurityAgent` - returns sample audit
  - [ ] `MockDatabaseAgent` - returns sample schema
- [ ] Unit tests for each component (from above checklists)
- [ ] Integration tests (end-to-end)
  - [ ] `test_e2e_website_build()` - full workflow
  - [ ] `test_e2e_security_audit()` - security only
  - [ ] `test_e2e_with_failure()` - failure handling
  - [ ] `test_e2e_with_conflicts()` - conflict resolution
  - [ ] `test_e2e_cost_tracking()` - cost calculation
- [ ] Performance tests
  - [ ] `test_parallel_vs_serial_latency()` - timing
  - [ ] `test_worker_pool_concurrency()` - QPS
- [ ] Edge cases
  - [ ] `test_empty_task_list()`
  - [ ] `test_all_tasks_fail()`
  - [ ] `test_mixed_success_failure()`
  - [ ] `test_task_with_dependencies()`
- [ ] Mocking strategy
  - [ ] Mock anthropic.Anthropic for testing
  - [ ] Mock gateway.call_model_for_agent()
  - [ ] Patch cost_tracker.log_cost_event()
- [ ] Use pytest fixtures
  - [ ] @pytest.fixture config
  - [ ] @pytest.fixture executor
  - [ ] @pytest.fixture mock_agents

**Test Coverage Target: >85%**

---

## Phase 3: Gateway Integration (Week 3)

### 3.1 Modify config.json

**Checklist:**

- [ ] Add "parallel_execution" section
  - [ ] enabled: true/false
  - [ ] worker_pools.codegen: max_concurrent, timeout
  - [ ] worker_pools.security: max_concurrent, timeout
  - [ ] worker_pools.database: max_concurrent, timeout
  - [ ] pm_coordinator: decomposition_model, reasoning_effort
  - [ ] result_aggregation: strategy, conflict_resolution
- [ ] Verify JSON is valid: `python -m json.tool config.json`
- [ ] Test load_config in code

---

### 3.2 Modify gateway.py

**Checklist:**

- [ ] Import new modules at top
  ```python
  from parallel_executor import ParallelExecutor, ParallelExecutorConfig
  from pm_coordinator import PMCoordinator
  from failure_handler import FailureHandler
  ```
- [ ] Create new endpoint: `POST /api/execute-parallel`
  - [ ] Accept message, sessionKey, project, force_parallel
  - [ ] Call pm_coordinator.decompose_into_parallel_tasks()
  - [ ] Call parallel_executor.execute_parallel()
  - [ ] Log costs with cost_tracker
  - [ ] Return execution_id + task details
- [ ] Create new endpoint: `GET /api/execution/{execution_id}`
  - [ ] Retrieve execution state
  - [ ] Return task statuses + results
  - [ ] Return final_response if complete
- [ ] Modify existing `/api/chat` endpoint
  - [ ] Detect if request is candidate for parallel execution
  - [ ] Route to either `/api/execute-parallel` or serial agent_router
  - [ ] Decision logic in routing
- [ ] Error handling
  - [ ] Return 400 if invalid request
  - [ ] Return 404 if execution not found
  - [ ] Return 500 if internal error (with logging)
- [ ] Add timing instrumentation
  - [ ] Record request start time
  - [ ] Record execution completion time
  - [ ] Log latency metrics
- [ ] Add cost tracking
  - [ ] Track PM decomposition cost
  - [ ] Track each agent task cost
  - [ ] Track aggregation cost
  - [ ] Sum to total

**Testing:**

- [ ] Test endpoint response schema
- [ ] Test error cases
- [ ] Test cost calculation
- [ ] Integration test with real agents

---

### 3.3 Modify agent_router.py

**Checklist:**

- [ ] Import TaskDistributor
- [ ] Add method: `should_use_parallel_execution()`
  - [ ] Check project complexity
  - [ ] Check if PM recommends parallel
  - [ ] Check configuration enabled
  - [ ] Return bool
- [ ] Modify `select_agent()` method
  - [ ] If should_use_parallel_execution() → return "parallel_executor"
  - [ ] Otherwise → existing routing logic
- [ ] Add new routing case for "parallel_executor"
  - [ ] In gateway.py route handling
  - [ ] Call /api/execute-parallel

---

## Phase 4: Testing & Validation (Week 4)

### 4.1 Functional Testing

**Checklist:**

- [ ] Run all unit tests
  ```bash
  python -m pytest test_parallel_executor.py -v
  ```

  - [ ] Result: All tests passing
  - [ ] Coverage: >85%
- [ ] Run integration tests
  - [ ] Test e2e website build
  - [ ] Test e2e security audit
  - [ ] Test e2e with failures
- [ ] Manual testing with real agents
  - [ ] Test with Claude Opus + MiniMax backend
  - [ ] Record latency
  - [ ] Record cost
  - [ ] Verify quality
- [ ] Backward compatibility
  - [ ] Serial execution still works
  - [ ] No breaking changes to existing API
  - [ ] Existing code unaffected

---

### 4.2 Performance Testing

**Checklist:**

- [ ] Latency test: Restaurant website build
  - [ ] Serial: Expected ~240s
  - [ ] Parallel: Expected ~150s
  - [ ] Target: >30% speedup
- [ ] Throughput test: 10 concurrent executions
  - [ ] No crashes
  - [ ] All complete within timeout
  - [ ] Resources stay reasonable
- [ ] Load test: 100 concurrent tasks
  - [ ] Queue management working
  - [ ] No memory leaks
  - [ ] Worker pools stable
- [ ] Cost test: 50 random projects
  - [ ] Cost tracking accurate
  - [ ] Parallel overhead <10%
  - [ ] Compare serial vs parallel cost difference

---

### 4.3 Error Testing

**Checklist:**

- [ ] Timeout handling
  - [ ] Task timeout → retries
  - [ ] Max retries → failure
  - [ ] Partial results returned
- [ ] Agent unavailable
  - [ ] Agent crashes → failure logged
  - [ ] Graceful degradation active
  - [ ] Client notified
- [ ] Dependency failure
  - [ ] Backend fails → Security blocked
  - [ ] Partial results aggregated
- [ ] Conflict resolution
  - [ ] Multiple conflicts handled
  - [ ] Security-first applied
  - [ ] Results merged correctly

---

### 4.4 Documentation

**Checklist:**

- [ ] Code docstrings
  - [ ] All public methods documented
  - [ ] All classes documented
  - [ ] Complex logic explained
- [ ] Inline comments
  - [ ] Tricky sections explained
  - [ ] Why (not just what)
- [ ] README updates
  - [ ] Add parallel execution section
  - [ ] Link to full documentation
  - [ ] Quick start example
- [ ] Runbook creation
  - [ ] How to enable parallel execution
  - [ ] How to tune parameters
  - [ ] How to troubleshoot

---

## Deployment Checklist

### Pre-Deployment

- [ ] All tests passing (100% pass rate required)
- [ ] Code review complete
- [ ] Documentation reviewed
- [ ] Performance benchmarks met
- [ ] Cost impact acceptable
- [ ] No breaking changes verified
- [ ] Rollback plan documented

### Deployment

- [ ] Create feature branch: `feature/parallel-execution`
- [ ] Commit all changes with clear messages
  ```
  feat: Add parallel execution framework
  feat: Implement worker pools
  feat: Add PM decomposition logic
  feat: Integrate with gateway
  ```
- [ ] Create pull request
- [ ] Code review (self-review minimum)
- [ ] Run final test suite
- [ ] Merge to main
- [ ] Deploy to staging
- [ ] Monitor logs for errors
- [ ] Run smoke tests on staging
- [ ] Deploy to production (canary, 10% traffic)
- [ ] Monitor metrics (latency, cost, errors)
- [ ] Ramp up to 100% if stable

### Post-Deployment

- [ ] Monitor error rates (should stay <1%)
- [ ] Monitor latency (p95 <200s target)
- [ ] Monitor cost (should save 30-40% for large projects)
- [ ] Gather user feedback
- [ ] Document any issues found
- [ ] Plan improvements for v1.1

---

## Success Metrics

### Must Have (v1.0)

- [ ] All tests passing (100%)
- [ ] Parallel execution 1.5x faster for large projects
- [ ] No increase in error rate
- [ ] Cost tracking accurate (within 5%)
- [ ] Documentation complete
- [ ] Backward compatible

### Nice to Have (v1.0)

- [ ] 2.0x faster for very large projects
- [ ] <5% cost overhead
- [ ] <100ms routing decision time

### Future (v1.1+)

- [ ] Streaming results to client
- [ ] Smart caching (reuse results)
- [ ] Multi-PM support
- [ ] Dynamic pool scaling

---

## Timeline

```
Week 1 (Phase 1):
  Mon-Tue: parallel_executor.py + worker_pools.py
  Wed: task_distributor.py
  Thu: result_aggregator.py
  Fri: Unit tests + debugging

Week 2 (Phase 2):
  Mon: pm_coordinator.py
  Tue: failure_handler.py
  Wed-Thu: Integration tests
  Fri: Bug fixes + cleanup

Week 3 (Phase 3):
  Mon: Modify config.json + gateway.py
  Tue-Wed: Endpoint testing
  Thu: Modify agent_router.py
  Fri: Integration testing

Week 4 (Phase 4):
  Mon-Tue: Functional testing
  Wed: Performance testing
  Thu: Error testing + documentation
  Fri: Deployment + monitoring

Total: ~4 weeks for v1.0
```

---

## Key Files Summary

| File                      | Size          | Purpose               | Status    |
| ------------------------- | ------------- | --------------------- | --------- |
| parallel_executor.py      | 450 LOC       | Core orchestrator     | To Create |
| worker_pools.py           | 380 LOC       | Agent pool management | To Create |
| task_distributor.py       | 220 LOC       | Task routing          | To Create |
| result_aggregator.py      | 320 LOC       | Result merging        | To Create |
| pm_coordinator.py         | 380 LOC       | PM decomposition      | To Create |
| failure_handler.py        | 280 LOC       | Error recovery        | To Create |
| test_parallel_executor.py | 650 LOC       | Tests                 | To Create |
| config.json               | 10 lines      | Configuration         | To Modify |
| gateway.py                | 50 lines      | New endpoints         | To Modify |
| agent_router.py           | 20 lines      | Routing logic         | To Modify |
| **Total New**             | **2,680 LOC** |                       |           |

---

## Notes

- All modules use async/await for concurrency
- No threading (better for I/O-bound work)
- Extensive logging at INFO/DEBUG levels
- Type hints on all public APIs
- > 85% test coverage required
- Configuration-driven (easy to tune)
- Backward compatible (non-breaking)
