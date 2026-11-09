# Use a merge queue instead of requiring up-to-date branches

A merge queue tests each ready pull request on top of the base branch and the pull requests ahead of it, so authors stop updating branches and rerunning CI before every merge. Required workflows must also run on merge_group.

- Playbook: [Keep CI ahead of a growing pull request queue](https://berrybox.io/playbooks/pr-volume.md)
- Saves: wait time and runner minutes
- Risk: medium
- Web page: https://berrybox.io/playbooks/pr-volume/merge-queue

## Signals in your baseline

- Branch protection or a ruleset requires branches to be up to date before merging (strict required status checks).
- Merged pull requests carry several "Merge branch 'main' into ..." commits or force-pushed rebases, each followed by a full CI run.
- The default branch goes red after merges that each passed CI on their own.

## Why it works

When branches must be up to date, each merge makes every other ready pull request stale. Its author updates the branch and waits for a full run again, and only one pull request can merge per run. With ten ready pull requests and a 15-minute run, the last one waits hours, and every run made stale along the way is thrown out.

A merge queue takes over that loop. When someone adds a ready pull request, GitHub creates a temporary branch with the latest base branch, the pull requests ahead in the queue and this one, and triggers `merge_group` so CI tests that exact combination. Groups build in parallel, so several pull requests merge per CI run. A failing pull request is removed and the groups behind it are rebuilt without it. The base branch only moves to commits whose required checks passed, so two changes that break only in combination are caught before merge.

## Apply it

Add `merge_group` to every workflow that reports a required check:

```yaml
name: CI

on:
  pull_request:
  merge_group:
    types: [checks_requested]
  push:
    branches: [main]

permissions:
  contents: read

concurrency:
  group: ${{ github.workflow }}-${{ github.event.pull_request.number || github.ref }}
  cancel-in-progress: ${{ github.event_name == 'pull_request' }}

jobs:
  test:
    runs-on: ubuntu-latest
    timeout-minutes: 30
    steps:
      - uses: actions/checkout@v7
      - run: make test
```

- `checks_requested` is the only activity type. `merge_group` accepts `branches` filters but not `paths`, so a path filter can't skip a merge group run.
- A merge group run checks out the group's temporary `gh-readonly-queue/main/...` branch. Its payload has no pull request, so `github.event.pull_request` is empty; `github.event.merge_group.base_sha` and `head_sha` describe the group.
- The concurrency key falls back to `github.ref`, which is unique per group, so groups never cancel each other.

Then a repository admin turns on "Require merge queue" in the ruleset or branch protection for the default branch. Starting points:

- **Build concurrency**: how many groups CI tests at once. Each one is a full run, so this is the queue's runner budget. Shopify ran CI on only the next three batches to keep cost bounded.
- **Merge limits**: the maximum group size caps how many changes reach the base branch at once. Keep it near what you deploy at a time.
- **Status check timeout**: a little above the required workflow's p90 wall time from the [baseline](https://berrybox.io/playbooks/baseline.md), so a hung run doesn't hold the queue.
- **Only merge non-failing pull requests**: leave it on. Turned off, a group merges when its last pull request passes, even if an earlier one failed. That rides over flaky failures but can put failing commits into the base branch's history.

### Without a merge queue

Merge queues are available for public repositories owned by organizations and for private ones on GitHub Enterprise Cloud. Elsewhere, Ramp dropped the up-to-date requirement, let pull requests merge in parallel and blocked deploys until CI passed on the default branch. Pull requests that add database migrations still had to be current: each one changes a shared hash file, so two of them conflict in Git.

## Keep it safe

- A required check from a workflow without `merge_group` never reports on the group. The queue waits until the status check timeout, then removes the pull request. Add the trigger to every such workflow before you turn the queue on.
- Every required check must report on merge groups, including checks that only look at the pull request, such as title format. For those, a job that passes immediately on `merge_group` is fine, because combining pull requests can't change the answer. Never do that for builds or tests.
- Jobs that skip by changed paths should run in full on merge groups (see [skip unchanged paths](https://berrybox.io/playbooks/wasted-runs/skip-unchanged-paths.md)).
- Caches saved in a merge group run are scoped to its temporary branch, which no later run reads. Restore caches there and save them on pushes to `main`.
- Merge group runs execute the queued code with the repository's secrets, like a push to `main`. Review pull requests from forks before anyone queues them.
- Jumping the queue rebuilds every group behind it. Keep it for emergencies.
- Without a queue, the Ramp approach lets two incompatible changes reach `main`. Treat a red `main` as an incident that blocks deploys.

## Verify

- Queue a pull request with the merge button or `gh pr merge <number>`. `gh run list --event merge_group` should show a run for its group, and every required check should report on it.
- Watch the queue's timeline for pull requests removed by a timeout. Each one points at a required check that doesn't run on `merge_group`.
- After two weeks, rerun the [baseline](https://berrybox.io/playbooks/baseline.md). Runs of the `pull_request` workflow per merged pull request should fall, because authors no longer update and rerun, and new `merge_group` rows should show about one run per group.

## Sources

- GitHub: [GitHub blog: replace deploy trains with a merge queue for the GitHub.com monorepo](https://github.blog/engineering/engineering-principles/how-github-uses-merge-queue-to-ship-hundreds-of-changes-every-day/). The average wait time to ship a change was reduced by 33%.
- Shopify: [Shopify Engineering: batch queued pull requests, test only the next three batches and tolerate flaky failures](https://shopify.engineering/successfully-merging-work-1000-developers)
- Uber: [Uber blog: prioritize the speculative merge queue builds most likely to be needed](https://www.uber.com/us/en/blog/slashing-ci-costs-at-uber/)
- Ramp: [Ramp Builders: drop the up-to-date requirement and gate deploys on main instead](https://builders.ramp.com/post/merge-queues). The average time to merge decreased from over an hour to 12 minutes, the length of one test run.
