# GitHub Integration Setup Guide

## Quick Start

### 1. Add Router to gateway.py

```python
# At the top of gateway.py (with other imports)
from github_integration import router as github_router

# In your FastAPI app setup (after creating the FastAPI app instance)
app.include_router(github_router)
```

### 2. Integrate with autonomous_runner.py

```python
# In autonomous_runner.py, after delivery phase completes
from github_integration import apply_auto_delivery_config

async def _run_job_pipeline(self, job: dict) -> dict:
    # ... existing code ...

    # After the delivery phase:
    if result["success"] and job.get("delivery_config", {}).get("auto_pr"):
        try:
            apply_auto_delivery_config(job)
        except Exception as e:
            logger.warning(f"Auto-delivery failed for job {job_id}: {e}")

    return result
```

### 3. Modify intake_routes.py to Accept delivery_config

```python
# In the IntakeRequest model
class IntakeRequest(BaseModel):
    project_name: str = Field(..., min_length=1, max_length=200)
    description: str = Field(..., min_length=10, max_length=10000)
    task_type: str = Field(...)
    priority: str = Field(default="P2")
    budget_limit: Optional[float] = Field(default=None, ge=0)
    contact_email: Optional[str] = Field(default=None, max_length=200)

    # NEW FIELD for GitHub integration
    delivery_config: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Optional: {auto_pr: bool, repo: 'owner/repo', auto_merge: bool}"
    )

# In submit_intake function, preserve delivery_config
job = {
    # ... existing fields ...
    "delivery_config": req.delivery_config,  # Add this line
}
```

## Configuration

### Job Submission with Auto-Delivery

```bash
curl -X POST http://localhost:18789/api/intake \
  -H "Content-Type: application/json" \
  -d '{
    "project_name": "Add OAuth2 support",
    "description": "Implement OAuth2 with Google and GitHub providers",
    "task_type": "feature_build",
    "priority": "P1",
    "budget_limit": 10.0,
    "contact_email": "client@example.com",
    "delivery_config": {
      "auto_pr": true,
      "repo": "miles0sage/my-project",
      "auto_merge": false
    }
  }'
```

### Manual Delivery After Job Completion

```bash
# After job is done, deliver to GitHub
curl -X POST http://localhost:18789/api/jobs/{job_id}/deliver-github \
  -H "Content-Type: application/json" \
  -d '{
    "repo": "miles0sage/my-project",
    "base_branch": "main",
    "auto_merge": false
  }'
```

## Prerequisites

### 1. GitHub CLI Setup

```bash
# Check if gh is installed
gh --version

# If not installed (on Ubuntu/Debian):
sudo apt-get install gh

# On macOS:
brew install gh

# Authenticate
gh auth login

# Verify authentication
gh auth status
```

### 2. Git Configuration (per project)

The module will auto-configure git user for each repo:

```bash
git config user.name "OpenClaw AI"
git config user.email "openclaw@agency.local"
```

### 3. GitHub Access

The authenticated user must have:

- Push access to target repositories
- PR creation privileges
- Merge privileges (if auto_merge is enabled)

## Troubleshooting

### Issue: "gh command not found"

```bash
# Install gh CLI
curl -sS https://webi.sh/gh | sh

# Or verify it's in PATH
which gh

# Add to PATH if needed
export PATH="$HOME/.local/bin:$PATH"
```

### Issue: "Not authenticated with GitHub"

```bash
gh auth login
# Follow interactive prompts to authenticate
```

### Issue: "Permission denied for repository"

```bash
# Check your access
gh repo view owner/repo

# Verify SSH key is configured (if using SSH auth)
ssh -T git@github.com

# Or use HTTPS with PAT
gh auth login --with-token < token.txt
```

### Issue: "Branch creation failed"

Check that:

1. Repository exists and is accessible
2. Base branch exists (usually `main`)
3. User has push access
4. No rate limiting issues: `gh api rate-limit`

### Issue: "PR creation failed"

Check that:

1. All files were committed successfully
2. Branch exists on remote
3. Base branch is correct
4. PR body isn't too large (GitHub has limits)

## Monitoring

### Check Delivery Status

```bash
# Get status of a specific job's PR
curl http://localhost:18789/api/jobs/{job_id}/pr

# List all deliveries
curl http://localhost:18789/api/deliveries

# Filter by status
curl http://localhost:18789/api/deliveries?status=merged
curl http://localhost:18789/api/deliveries?status=open
curl http://localhost:18789/api/deliveries?status=delivered
```

### View Delivery Logs

Delivery records are stored in:

```
/tmp/openclaw_github_deliveries.json
```

View with:

```bash
cat /tmp/openclaw_github_deliveries.json | python3 -m json.tool
```

### Monitor Job Logs

Job status and logs:

```bash
# Get full job details
curl http://localhost:18789/api/jobs/{job_id}

# Get progress (phases completed, cost, logs)
curl http://localhost:18789/api/jobs/{job_id}/progress

# Get intake stats
curl http://localhost:18789/api/intake/stats
```

## Webhook Setup (Optional)

To receive notifications when PRs are merged:

1. Go to your GitHub repository
2. Settings → Webhooks → Add webhook
3. Payload URL: `https://your-domain.com/api/github/webhook`
4. Content type: `application/json`
5. Events:
   - Pull request
   - Check runs (optional)
6. Active: ✓
7. Add webhook

Module will automatically:

- Update delivery status to "merged" when PR is merged
- Log the merge event in job logs
- Clean up feature branches (optional, can be added)

## Cost Integration

The delivery process integrates with existing cost tracking:

1. **Job cost**: All API calls made during job execution are tracked
2. **Delivery overhead**: PR creation and management cost negligible (<$0.01)
3. **Cost reporting**: PR body includes full breakdown by agent
4. **Budget enforcement**: Respects job's budget_limit

Example cost breakdown in PR:

```
### Cost Breakdown
- **CodeGen Elite**: $0.45
- **CodeGen Pro**: $0.23
- **Pentest AI**: $0.12

**Total Cost**: $0.80
**Budget Limit**: $5.00
```

## Examples

### Example 1: Simple Feature Delivery

```bash
# Submit job with auto-delivery
curl -X POST http://localhost:18789/api/intake \
  -H "Content-Type: application/json" \
  -d '{
    "project_name": "Fix login form validation",
    "description": "Add client-side and server-side validation to login form",
    "task_type": "bug_fix",
    "priority": "P1",
    "delivery_config": {
      "auto_pr": true,
      "repo": "miles0sage/my-app",
      "auto_merge": false
    }
  }'

# Job ID returned: abc-123-def

# After ~2-5 minutes, check status
curl http://localhost:18789/api/jobs/abc-123-def/pr

# Response shows PR created and merged status
```

### Example 2: Complex Feature with Manual Delivery

```bash
# Submit job without auto-delivery (complex task)
curl -X POST http://localhost:18789/api/intake \
  -H "Content-Type: application/json" \
  -d '{
    "project_name": "Refactor authentication system",
    "description": "Complete rewrite of auth module with better separation of concerns",
    "task_type": "feature_build",
    "priority": "P1",
    "budget_limit": 50.0
  }'

# Job ID returned: xyz-789-ghi

# After job completes (~5-10 minutes)
# Manually deliver to GitHub
curl -X POST http://localhost:18789/api/jobs/xyz-789-ghi/deliver-github \
  -H "Content-Type: application/json" \
  -d '{
    "repo": "miles0sage/my-app",
    "base_branch": "dev",
    "auto_merge": false
  }'

# PR created at: https://github.com/miles0sage/my-app/pull/42
# Review and merge manually in GitHub
```

### Example 3: Multi-Project Delivery

```bash
# Different projects with different repos
jobs = [
  {
    "project_name": "Add logging to API",
    "delivery_config": {
      "auto_pr": true,
      "repo": "acme/api-service"
    }
  },
  {
    "project_name": "Update dashboard UI",
    "delivery_config": {
      "auto_pr": true,
      "repo": "acme/dashboard"
    }
  }
]

# Each creates PR in its own repo
# Can monitor all at once:
curl http://localhost:18789/api/deliveries
```

## Performance Notes

1. **Branch creation**: ~500ms (gh API call)
2. **Commit + push**: ~2-5s (depends on file size and network)
3. **PR creation**: ~1-2s (gh CLI + GitHub API)
4. **Total delivery time**: ~5-10 seconds per job

All operations are async and non-blocking, so multiple jobs can be delivered in parallel.

## Security Considerations

1. **Authentication**: Uses existing gh CLI auth (no new credentials stored)
2. **API keys**: No API keys stored in code (uses gh's credential manager)
3. **Repo access**: Limited to repositories user has access to
4. **Audit trail**: All deliveries logged with timestamps and job IDs
5. **Webhook verification**: Can add GitHub webhook signing verification

## Next Steps

1. Add router to gateway.py (5 min)
2. Test with a sample job (10 min)
3. Set up GitHub webhook for notifications (5 min)
4. Enable auto-delivery on jobs (instant)
5. Monitor delivery success rate (ongoing)
