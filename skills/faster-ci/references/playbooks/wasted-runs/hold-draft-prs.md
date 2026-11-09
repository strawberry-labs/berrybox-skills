# Hold expensive checks until a draft pull request is ready for review

Skip the slow jobs while a pull request is still a draft and start them when it is marked ready, so pushes of unfinished work get quick checks instead of the full suite.

- Playbook: [Stop paying for runs nobody needs](https://berrybox.io/playbooks/wasted-runs.md)
- Saves: runner minutes
- Risk: medium
- Web page: https://berrybox.io/playbooks/wasted-runs/hold-draft-prs

## Signals in your baseline

- The pull_request trigger has no types list, or one without ready_for_review, and no job reads github.event.pull_request.draft.
- `gh pr list --draft --json number,commits` shows drafts that collect many pushes, and every push runs the same jobs as a ready pull request.
- The slowest jobs in the baseline (end-to-end, integration, extra operating systems) run on every pull_request push.

## Why it works

A draft tells reviewers the work isn't finished. Authors and coding agents push to drafts often, to back up work, share progress or try a fix, and each push runs the whole workflow. Nobody reads the end-to-end results of a commit that will be replaced an hour later. Holding the slow jobs until the pull request is marked ready leaves drafts with the cheap checks, which still catch most mistakes in a few minutes.

GitHub doesn't start `pull_request` workflows when a draft is marked ready unless you ask for it: the default activity types are `opened`, `synchronize` and `reopened`. Adding `ready_for_review` starts a full run on the same commit at the moment someone wants a review. GitLab's own project goes a step further and runs a predicted subset of tests until a merge request is approved, then the full suite.

## Apply it

```yaml
name: CI

on:
  pull_request:
    types: [opened, synchronize, reopened, ready_for_review]
  merge_group:
  push:
    branches: [main]

permissions:
  contents: read

jobs:
  lint:
    runs-on: ubuntu-latest
    timeout-minutes: 10
    steps:
      - uses: actions/checkout@v7
      - run: make lint

  e2e:
    if: ${{ !github.event.pull_request.draft }}
    runs-on: ubuntu-latest
    timeout-minutes: 30
    steps:
      - uses: actions/checkout@v7
      - run: make e2e

  ci-ok:
    if: always()
    needs: [lint, e2e]
    runs-on: ubuntu-latest
    timeout-minutes: 5
    steps:
      - if: contains(needs.*.result, 'failure') || contains(needs.*.result, 'cancelled')
        run: exit 1
```

- Setting `types` replaces the defaults, so list all four. Without `ready_for_review`, marking a draft ready starts nothing.
- A condition that starts with `!` needs the `${{ }}` wrapper, because YAML reads a leading `!` as a tag.
- `push` and `merge_group` runs carry no pull request in their payload. `github.event.pull_request.draft` is empty there, `!` turns it into true, and those runs always run every job.
- Put the condition on each expensive job, or on the first job of a chain, since jobs that `need` a skipped job are skipped too.
- `lint` has no condition, so drafts still get fast feedback. Keep the checks authors rely on while iterating, such as lint, type checks and fast unit tests, and hold the rest.

### Cancel the run when a pull request goes back to draft

If the workflow uses the concurrency group from [cancel stale runs](https://berrybox.io/playbooks/wasted-runs/cancel-stale-runs.md), add `converted_to_draft` to `types`. Converting a pull request then starts a new run, which cancels the one in progress, and its held jobs skip. The unconditioned jobs would run again on the same commit, so give them `if: github.event.action != 'converted_to_draft'`.

## Keep it safe

- `ready_for_review` is what keeps this safe. A skipped job reports success, so after the last draft push every held check counts as passing. If marking the pull request ready doesn't start a new run, it can merge without the held jobs ever running. Check this before you merge the change, not after.
- A draft can't be merged, so held checks only matter once it leaves draft. Marking it ready starts a full run on the same commit, and the pull request then waits on that run's checks.
- Keep `merge_group` and default-branch `push` runs out of the condition. The `!github.event.pull_request.draft` form does that without extra clauses; if you write `github.event.pull_request.draft == false` instead, add `github.event_name != 'pull_request' ||` in front so the condition doesn't depend on how a missing value compares.
- Coding agents that open drafts and fix their own CI failures lose the held jobs' feedback until someone marks the pull request ready. Keep the checks they act on unconditioned, or have them run the slow suite before asking for review (see [verify before opening a pull request](https://berrybox.io/playbooks/pr-volume/verify-before-pr.md)).

## Verify

- Open a draft pull request and push to it. `gh pr checks <number>` should list `e2e` as skipped and `lint` as passing.
- Run `gh pr ready <number>`. A new run should start within a minute (`gh run list --branch <branch> --event pull_request`), and `e2e` should run on the same head commit.
- Confirm a push to `main` and a merge group run still execute every job.
- After a week, compare with the [baseline](https://berrybox.io/playbooks/baseline.md). Runner minutes for `pull_request` runs should fall by roughly the share that draft pushes used to take, while the `push` and `merge_group` rows stay the same.

## Sources

- Shopify: [checkout-kit: skip CI jobs on draft pull requests, run on ready_for_review and cancel runs on converted_to_draft](https://github.com/Shopify/checkout-kit/pull/284)
- Uber: [submitqueue: guard every job and the required-checks gate on draft state, keeping push and merge queue runs](https://github.com/uber/submitqueue/pull/180)
- GitLab: [GitLab development docs: run a predicted test subset until a merge request is approved, then the full suite](https://docs.gitlab.com/development/pipelines/)
