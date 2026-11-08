# Report templates

## Proposal

Show this before changing anything. Every "measured problem" needs a number from the baseline. Give savings as ranges, and say which are wall time (what developers wait for) and which are runner minutes (what you pay for).

| # | Play | Measured problem | Expected saving | Risk | Files |
|---|---|---|---|---|---|
| 1 | [Cancel runs a newer push replaced](https://berrybox.io/playbooks/wasted-runs/cancel-stale-runs) | `CI` has no concurrency group; 40% of pull request runs overlap a newer push | 15 to 25% fewer runner minutes on pull requests | low | `.github/workflows/ci.yml` |
| 2 | ... | ... | ... | ... | ... |

Then ask: "Which of these should I apply? For example: 1, 3."

## Pull request description

```markdown
## Why

Baseline from the last <N> days (<M> runs), measured with the BerryBox baseline script:

| Workflow (event) | p50 wall | p90 wall | p50 queue | Runner min/run | Long pole |
|---|---|---|---|---|---|
| CI (pull_request) | 14m10s | 19m02s | 6s | 58 | test (3m setup + 9m tests) |

## Changes

One commit per play, so each can be reviewed and reverted on its own.

1. **<Play title>** (<play URL>): <what changed>. Targets <metric and baseline number>. Expected: <saving>. Risk: <risk>.
2. ...

## Results

| Job or step | Baseline p50 | This branch | Runs measured |
|---|---|---|---|
| test / Install dependencies | 1m41s | 22s | 3 |

Measured: <what the runs above show>.
Not yet measured: <estimates, and what will show them, such as a week of default-branch runs>.

## Checks

- Required checks: <names>, all still reporting under the same names.
- Tests: <count> ran before and after.
```
