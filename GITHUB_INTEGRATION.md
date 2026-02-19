# OpenClaw GitHub Integration — Usage Guide

## Overview

The `github_integration.py` module enables OpenClaw to automatically create pull requests and deliver completed jobs to client GitHub repositories. It wraps the `gh` CLI tool and provides both a Python API and FastAPI endpoints.

## Features

### 1. GitHubClient Class

Low-level wrapper around `gh` CLI operations:

```python
from github_integration import GitHubClient

github = GitHubClient()

# Create a feature branch
await github.create_branch("owner/repo", "feature/my-change")

# Commit and push files
success, commit_hash = await github.commit_and_push(
    "owner/repo",
    "feature/my-change",
    {"/root/project/file.py": "Modified content"},
    "feat: add new feature"
)

# Create a PR
success, pr_url = await github.create_pr(
    "owner/repo",
    "feature/my-change",
    "My Feature Title",
    "## Description\nThis PR does X"
)

# Get PR status
status = await github.get_pr_status("owner/repo", 123)
# Returns: {status, checks_passed, reviews_approved, mergeable, merged, merged_at}

# Merge a PR
success, msg = await github.merge_pr("owner/repo", 123, method="squash")
```

### 2. Job Delivery Workflow

High-level function that handles the complete delivery process:

```python
from github_integration import deliver_job_to_github

result = await deliver_job_to_github(
    job_id="abc-123",
    repo="miles0sage/my-project",
    files_changed={
        "/root/my-project/src/app.py": "Added feature X",
        "/root/my-project/tests/test_app.py": "Added tests for X",
    },
    base_branch="main",
    auto_merge=False
)

# Returns:
# {
#     "job_id": "abc-123",
#     "repo": "miles0sage/my-project",
#     "pr_number": 42,
#     "pr_url": "https://github.com/miles0sage/my-project/pull/42",
#     "branch": "openclaw/job-abc12345",
#     "status": "delivered",
#     "created_at": "2026-02-19T...",
#     "merged": false,
#     "cost_breakdown": {...},
#     "total_cost": 1.23
# }
```

### 3. FastAPI Endpoints

#### POST /api/jobs/{job_id}/deliver-github

Deliver a completed job to GitHub:

```bash
curl -X POST http://localhost:18789/api/jobs/abc-123/deliver-github \
  -H "Content-Type: application/json" \
  -d '{
    "repo": "miles0sage/my-project",
    "base_branch": "main",
    "auto_merge": false
  }'
```

Response:

```json
{
  "success": true,
  "pr_url": "https://github.com/miles0sage/my-project/pull/42",
  "pr_number": 42,
  "branch": "openclaw/job-abc12345",
  "status": "delivered"
}
```

#### GET /api/jobs/{job_id}/pr

Get the GitHub PR status for a delivered job:

```bash
curl http://localhost:18789/api/jobs/abc-123/pr
```

Response:

```json
{
  "job_id": "abc-123",
  "pr_number": 42,
  "pr_url": "https://github.com/miles0sage/my-project/pull/42",
  "branch": "openclaw/job-abc12345",
  "repo": "miles0sage/my-project",
  "delivered_at": "2026-02-19T...",
  "status": "OPEN",
  "checks_passed": true,
  "reviews_approved": false,
  "mergeable": "MERGEABLE",
  "merged": false,
  "merged_at": null,
  "cost": 1.23,
  "auto_merge": false
}
```

#### POST /api/github/webhook

Receive GitHub webhooks for PR events:

```bash
# GitHub sends POST with PR event payload
# Module listens for: opened, closed, merged, synchronize
# Updates delivery records automatically
```

#### GET /api/deliveries

List all GitHub deliveries:

```bash
curl http://localhost:18789/api/deliveries?status=merged&limit=50
```

Response:

```json
{
  "deliveries": [
    {
      "job_id": "abc-123",
      "repo": "miles0sage/my-project",
      "pr_number": 42,
      "pr_url": "https://github.com/miles0sage/my-project/pull/42",
      "status": "merged",
      "branch": "openclaw/job-abc12345",
      "created_at": "2026-02-19T...",
      "merged": true,
      "merged_at": "2026-02-19T...",
      "total_cost": 1.23
    }
  ],
  "total": 1,
  "limit": 50,
  "offset": 0
}
```

### 4. Integration with gateway.py

Add the router to your FastAPI app:

```python
from fastapi import FastAPI
from github_integration import router as github_router

app = FastAPI()
app.include_router(github_router)
```

### 5. Auto-Delivery Configuration

Jobs can include a delivery config for automatic PR creation:

```python
# When submitting a job via /api/intake:
{
  "project_name": "Add auth feature",
  "description": "Add OAuth2 support",
  "task_type": "feature_build",
  "priority": "P1",

  # New field for auto-delivery:
  "delivery_config": {
    "auto_pr": true,
    "repo": "miles0sage/my-project",
    "auto_merge": false
  }
}
```

After the job completes (status=done), the autonomous runner will automatically:

1. Create a feature branch
2. Commit all changes
3. Open a PR with job summary and cost breakdown
4. Store delivery record

Example in autonomous_runner.py:

```python
from github_integration import apply_auto_delivery_config

async def _run_job_pipeline(self, job: dict) -> dict:
    # ... run all 5 phases ...

    # After delivery phase completes:
    if result["success"]:
        apply_auto_delivery_config(job)
```

### 6. PR Body Template

The module automatically generates PR bodies with:

- Job ID and description
- Assigned agent
- Task priority
- Execution phases completed
- Cost breakdown per agent
- Total cost vs budget limit
- Files modified with descriptions
- Verification results
- OpenClaw credit line

Example PR body:

```markdown
## OpenClaw Job Delivery

**Job ID**: abc12345
**Task**: Add OAuth2 authentication
**Agent**: CodeGen Elite
**Priority**: P1

### Task Description

Implement OAuth2 support for Google and GitHub providers with PKCE flow for security.

### Execution Phases

✅ Phases Completed: research, plan, execute, verify, deliver

Current Status: `done`

### Cost Breakdown

- **CodeGen Elite**: $0.45
- **CodeGen Pro**: $0.23
- **Pentest AI**: $0.12

**Total Cost**: $0.80
**Budget Limit**: $5.00

### Files Modified

- **src/auth/oauth.py**: Implemented OAuth2 providers
- **src/auth/pkce.py**: Added PKCE flow for security
- **tests/test_oauth.py**: Comprehensive OAuth2 tests
- **config.example.json**: Added OAuth credentials template

### Verification Results

✅ All phases completed successfully

---

🤖 Delivered by [OpenClaw AI Agency](https://github.com/Miles0sage/openclaw)
```

## Prerequisites

1. **gh CLI installed**: `gh --version` should work
2. **GitHub authentication**: `gh auth status` should show authenticated
3. **Repository access**: User must have push access to target repos
4. **Local repo clones**: Projects must be cloned locally for git operations

## Error Handling

The module includes comprehensive error handling:

- Branch creation failures → logged and returned
- Commit/push failures → detailed subprocess output
- PR creation failures → webhook fallback for retry
- Network timeouts → automatic retry with backoff
- Missing job data → HTTP 404 response

## Storage

Delivery records are persisted to `/tmp/openclaw_github_deliveries.json`:

```json
{
  "job-id-123": {
    "job_id": "job-id-123",
    "repo": "miles0sage/project",
    "pr_number": 42,
    "pr_url": "https://github.com/...",
    "branch": "openclaw/job-abc12345",
    "status": "delivered",
    "created_at": "2026-02-19T...",
    "merged": false,
    "auto_merge": false,
    "cost_breakdown": {...},
    "total_cost": 1.23
  }
}
```

## Testing (Dry-Run Mode)

For testing without actual GitHub calls:

```python
github = GitHubClient(dry_run=True)

# All operations log instead of executing
await github.create_branch("owner/repo", "test-branch")
# Output: [DRY RUN] would create branch test-branch in owner/repo
```

## Cost Integration

The module integrates with the existing cost tracking:

1. **Delivery cost**: Included in job's total_cost (from execution phases)
2. **Per-agent breakdown**: Already tracked by autonomous_runner
3. **Budget enforcement**: Respects job's budget_limit
4. **Reporting**: PR body includes full cost breakdown

## Workflow Example

### Step 1: Submit a job with auto-delivery config

```bash
curl -X POST http://localhost:18789/api/intake \
  -H "Content-Type: application/json" \
  -d '{
    "project_name": "Add OAuth2 auth",
    "description": "Implement OAuth2 support for Google and GitHub",
    "task_type": "feature_build",
    "priority": "P1",
    "budget_limit": 5.0,
    "delivery_config": {
      "auto_pr": true,
      "repo": "miles0sage/my-project",
      "auto_merge": false
    }
  }'
```

### Step 2: Monitor job progress

```bash
curl http://localhost:18789/api/jobs/{job_id}/progress
```

### Step 3: After job completes, delivery happens automatically

```bash
# PR is created and stored in delivery records
curl http://localhost:18789/api/jobs/{job_id}/pr
```

### Step 4: Monitor PR status and merge when ready

```bash
curl http://localhost:18789/api/deliveries?status=open
```

## Architecture Decisions

### 1. Why gh CLI instead of PyGithub?

- **Simplicity**: sh CLI is already authenticated and configured
- **Reliability**: Uses GitHub's official CLI tool
- **Security**: No need to store additional API keys
- **Extensibility**: Easy to add new gh commands as needed

### 2. Why subprocess instead of library?

- **Compatibility**: Works with existing GitHub auth setup
- **Async-friendly**: Can run in executor without blocking event loop
- **Error visibility**: Full stdout/stderr for debugging
- **Version agnostic**: Works with any gh version

### 3. Why separate delivery storage?

- **Audit trail**: Complete record of all PR deliveries
- **Webhook integration**: Easier to match GitHub events to jobs
- **Persistence**: Survives agent restarts
- **Analytics**: Track delivery success rates, merge times, etc.

### 4. Why job.delivery_config?

- **Flexibility**: Jobs can opt-in to auto-delivery
- **Traceability**: Delivery preferences stored with job
- **Extensibility**: Easy to add more config options later
- **Backward compatibility**: Existing jobs work unchanged

## Future Enhancements

1. **Deployment triggers**: Auto-deploy to production after PR merges
2. **Notifications**: Slack/email when PR is merged
3. **Diff analysis**: Show code metrics in PR (coverage, complexity, etc.)
4. **Branch protection**: Enforce reviewers, checks, status checks
5. **Review assignment**: Auto-assign reviewers based on code ownership
6. **Rollback support**: Create rollback PRs if production issues detected
7. **Cost attribution**: Link GitHub commits to job cost tracking
