# Cancel runs a newer push replaced

Group each workflow's runs by pull request so a new push cancels the run it made obsolete, and leave default-branch, release and deploy runs alone.

- Playbook: [Stop paying for runs nobody needs](https://berrybox.io/playbooks/wasted-runs.md)
- Saves: runner minutes
- Risk: low
- Web page: https://berrybox.io/playbooks/wasted-runs/cancel-stale-runs

## Signals in your baseline

- Workflows triggered by pull_request have no concurrency block.
- Runs of the same workflow overlap on one pull request because pushes land faster than a run finishes.
- Queue time rises during bursts of pushes from developers or agents.

## Why it works

Once a pull request has a newer commit, the run for the older commit can only report on code nobody will merge. GitHub's `concurrency` key puts runs into a named group, and `cancel-in-progress` stops the older run as soon as a newer one joins the group. The freed runners pick up work that still matters, which also cuts queue time when pushes arrive in bursts.

## Apply it

Add a workflow-level `concurrency` block to each workflow that validates pull requests:

```yaml
concurrency:
  group: ${{ github.workflow }}-${{ github.event.pull_request.number || github.ref }}
  cancel-in-progress: ${{ github.event_name == 'pull_request' }}
```

- `github.workflow` keeps different workflows from cancelling each other.
- The pull request number puts every push to one pull request in the same group. `github.ref` covers pushes and manual runs.
- The `cancel-in-progress` expression cancels only pull request runs. Runs on the default branch wait their turn instead, so every merged commit still gets a result.

If the workflow already has a `concurrency` block, change it rather than adding another. GitHub allows one block at the workflow level and one per job. See GitHub's guide to [controlling workflow concurrency](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/control-workflow-concurrency).

## Keep it safe

- Leave deploy, release, publish and migration workflows out, or set `cancel-in-progress: false` on them. Stopping those halfway can leave half-applied state.
- Don't key the group on `github.ref` alone in `pull_request_target` or `workflow_run` workflows. Their ref is the base branch, so unrelated pull requests would cancel each other. Use the pull request number from the event payload.
- A cancelled run reports as cancelled, not failed. Required checks show as pending until the newer run finishes, which is the behavior you want.
- Cancellation stops the step that is running, but steps with `if: always()` still run. Make sure cleanup steps don't assume the cancelled step finished.

## Verify

- Push two commits to a test pull request about a minute apart. The first run should show as cancelled within seconds of the second push.
- After a week, compare runner minutes per merged pull request with the baseline. Wall time per run shouldn't change; total minutes, and queue time in busy hours, should fall.
- Confirm that no default-branch run shows as cancelled.

## Sources

- Anthropic: [anthropic-sdk-python: cancel superseded CI runs](https://github.com/anthropics/anthropic-sdk-python/commit/c8e75ece9e407966ed077a8e4e924e7ebd041c71)
- Uber: [baseweb: add a concurrency group to the pull request check workflow](https://github.com/uber/baseweb/pull/5407)
- Stripe: [stripe-ios: cancel stale dead-code scans with a group keyed on the pull request number](https://github.com/stripe/stripe-ios/pull/7337)
