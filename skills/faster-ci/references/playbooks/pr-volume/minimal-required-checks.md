# Keep required checks fast and run heavy suites after merge

Every merge waits on the slowest required check. Require only fast, reliable checks on pull requests, and run the slow suites in the merge queue, on the default branch after merge or as optional pull request jobs.

- Playbook: [Keep CI ahead of a growing pull request queue](https://berrybox.io/playbooks/pr-volume.md)
- Saves: wait time and runner minutes
- Risk: medium
- Web page: https://berrybox.io/playbooks/pr-volume/minimal-required-checks

## Signals in your baseline

- The required checks in the baseline include the slowest jobs (end-to-end, VM, extra operating systems), and the required workflow's p90 wall time is several times its fastest job.
- A required aggregate job also waits on cache saves, artifact or coverage uploads and reporting steps that never decide pass or fail.
- Slow required jobs have a high rerun rate, so flaky failures unrelated to a change block its merge.

## Why it works

A pull request can't merge before its slowest required check finishes, and it can't merge at all while a flaky required check is red. Both costs land on every pull request, including the many that change nothing the slow suite covers. Most bugs that a long end-to-end, VM or multi-platform suite catches are rare enough that finding them right after merge costs less than holding up every merge.

Slack made that trade for its web app. Critical end-to-end tests, under 1% of the total, stayed required before merge. A larger set, under 10%, moved to a pipeline that runs on every commit after merge and blocks deploys, with failures routed to the owning team.

Keep required what catches most breakage quickly: build, lint, type checks, unit tests and a few critical flows. Move the rest to one of three places:

- the merge queue, which still tests before merge, but once per group instead of once per push;
- pushes to the default branch, where a failure blocks deploys and reaches the author;
- optional pull request jobs whose names aren't required, so authors see results without being blocked.

## Apply it

```yaml
name: CI

on:
  pull_request:
  merge_group:
  push:
    branches: [main]

permissions:
  contents: read

jobs:
  fast:
    runs-on: ubuntu-latest
    timeout-minutes: 15
    steps:
      - uses: actions/checkout@v7
      - run: make lint typecheck unit-test

  e2e:
    if: github.event_name != 'pull_request'
    runs-on: ubuntu-latest
    timeout-minutes: 45
    steps:
      - uses: actions/checkout@v7
      - run: make e2e

  ci-ok:
    if: always()
    needs: [fast, e2e]
    runs-on: ubuntu-latest
    timeout-minutes: 5
    steps:
      - if: contains(needs.*.result, 'failure') || contains(needs.*.result, 'cancelled')
        run: exit 1
```

- `ci-ok` is the only required check from this workflow. On pull requests, `e2e` reports as skipped and `ci-ok` passes when `fast` does.
- In merge groups and on `main`, `e2e` runs and `ci-ok` fails with it. A failing merge group removes the pull request from the queue. Without a queue, the failure shows on `main` after merge.
- To keep slow results visible on pull requests without blocking, run them in a second workflow triggered only by `pull_request`, under job names no required check uses, with its own concurrency group. Shopify's tecnix prefixes all of them with `extended / `.
- Steps that don't decide pass or fail, such as cache saves, coverage uploads and reports, belong in a job the required check doesn't `need`.

## Keep it safe

- Bugs the moved suites catch now land on the default branch, or bounce out of the merge queue. Make post-merge failures loud: block deploys on a red `main`, send the failure to the author or owning team and revert quickly. Otherwise new merges pile onto a broken branch.
- Choose what to move from CI history, not duration alone. A suite that often catches real bugs before merge should stay required. A slow suite whose failures are mostly flakes is a better candidate.
- Change the required list in two steps: require `ci-ok` once it has reported, then remove the names of jobs that no longer gate pull requests. A name that stays required after its job stops reporting blocks every merge.
- If individual matrix legs stay required, put the event condition on their steps instead of the job. A job-level `if` is evaluated before the matrix expands, so a skipped matrix reports one check under its unexpanded name and the leg names never report.

## Verify

- On a pull request, `gh pr checks <number> --required` should show `ci-ok` passing in about the `fast` job's time.
- `gh run list --event merge_group` or `--event push` should show `e2e` running and reporting.
- After two weeks, rerun the [baseline](https://berrybox.io/playbooks/baseline.md). The `pull_request` p50 and p90 wall time of the required workflow should drop to about the fast jobs' duration, and runner minutes per pull request should fall.
- Track how often the merge queue or `main` fails on the moved suites. Move a suite back if it keeps catching bugs after merge.

## Sources

- Slack: [Slack Engineering: keep under 1% of end-to-end tests before merge and run a larger set after each merge](https://slack.engineering/balancing-safety-and-velocity-in-ci-cd-at-slack/). P95 test turnaround per commit fell from consistently above 30 minutes to consistently below 18, with no measurable increase in customer-reported defects.
- OpenAI: [codex: split fast pull request Rust checks from a full Cargo matrix that runs after merge on main](https://github.com/openai/codex/pull/16072)
- Shopify: [tecnix: gate pull requests on component tests, run VM and installer tests on main and the merge queue, and add optional extended jobs](https://github.com/Shopify/tecnix/pull/74)
- Linear: [Linear: move a cache-marker write out of the final required check into a job that gates nothing](https://linear.app/now/ci-bottleneck-reworked#minimize-what%27s-on-the-critical-path). The change took 42 seconds off the merge path for every API pull request and merge-queue entry.
