# Tests

## Test Organization

- **`tests/local/`** - Tests that don't use billable, third-party API calls
- **`tests/billable/`** - Tests that use third-party APIs (OpenAI, Anthropic, etc.)

## CI/CD Integration

### Local Tests (Automatic)
- **Workflow**: `.github/workflows/test-local.yml`
- **Trigger**: Every push to any branch
- **Command**: `pytest -v -s tests/local/`
- **Cost**: Free - no external API calls

### Billable Tests (Manual Approval Required)
- **Workflow**: `.github/workflows/test-billable.yml`
- **Trigger**: 
  - Manual trigger via GitHub Actions UI (`workflow_dispatch`)
  - Automatically on PRs to main branch (but requires approval)
- **Command**: `pytest -v -s tests/billable/`
- **Cost**: Uses external LLM APIs
- **Access**: Requires admin approval through GitHub Environment protection

#### How to Run Billable Tests

1. **From a Pull Request** (Recommended):
   - When you open a PR to main, billable tests automatically queue but wait for approval
   - In the PR's "Checks" section, you'll see "Test Billable (Requires Approval) - Waiting for approval"
   - Admins will see a **"Review deployments"** button directly in the PR
   - Click the button → Approve → Tests run immediately
   - Results appear in the PR checks

2. **Manual Trigger** (for testing outside of PRs):
   - Go to Actions tab → "Test Billable (Requires Approval)" workflow
   - Click "Run workflow" → Enter reason → Run
   - Admins can run immediately; others need approval

### GitHub Environment Configuration

The repository has a `billable-tests` environment configured with:
- **Required reviewers**: Repository admins
- **Prevent self-review**: Enabled (triggerer cannot approve their own run)
- **Branch restrictions**: Only main and protected branches

This ensures billable tests can only be run with explicit admin approval.

### test_api_calls.py

For `test_api_calls.py`, the user progam is executed as a replay by the server. So you need to run `ao-server logs` to see the output of the user program (e.g., how it crashed).

