# Skip jobs whose inputs didn't change, without stranding required checks

Detect changed paths in a first job, skip unaffected jobs with job-level if conditions and require one aggregate job, so small pull requests stop running everything while required checks keep reporting.

- Playbook: [Stop paying for runs nobody needs](https://berrybox.io/playbooks/wasted-runs.md)
- Saves: wait time and runner minutes
- Risk: medium
- Web page: https://berrybox.io/playbooks/wasted-runs/skip-unchanged-paths

## Signals in your baseline

- Recent docs-only or single-package pull requests ran every build and test job (compare `gh pr view <n> --json files` with `gh pr checks <n>`).
- A workflow whose jobs are required checks filters its pull_request trigger with paths or paths-ignore, and some pull requests sit at "Waiting for status to be reported".
- The repository holds several packages, services or languages, and each job builds from only part of the tree.

## Why it works

Most pull requests touch a small part of the repository. A job whose inputs didn't change would repeat the result it already produced on the base branch. A small `changes` job reads the list of changed files in a few seconds and sets one output per area. Each expensive job checks its output in a job-level `if`, and a skipped job never gets a runner.

Where you filter decides what branch protection sees:

- A workflow skipped by a trigger-level `paths` or `paths-ignore` filter never starts, so its checks never report. A required check from that workflow stays at "Waiting for status to be reported" and the pull request can't merge.
- A job skipped by a job-level `if` reports `skipped`, which counts as passing.
- A job whose `needs` failed is also skipped, so a required job downstream of a failure can pass without running.

The pattern below handles all three: filter at the job level, and make one aggregate job that always runs the only required check.

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
  changes:
    runs-on: ubuntu-latest
    timeout-minutes: 5
    permissions:
      contents: read
      pull-requests: read
    outputs:
      api: ${{ steps.filter.outputs.api || 'true' }}
      web: ${{ steps.filter.outputs.web || 'true' }}
    steps:
      - id: filter
        if: github.event_name == 'pull_request'
        uses: dorny/paths-filter@ceb8a2b8f2d89434be7ff52d3de7ec3738c5cc9d # v4.0.3
        with:
          filters: |
            shared: &shared
              - '.github/workflows/**'
              - 'package.json'
              - 'pnpm-lock.yaml'
              - 'packages/shared/**'
            api:
              - *shared
              - 'api/**'
            web:
              - *shared
              - 'web/**'

  api:
    needs: changes
    if: needs.changes.outputs.api == 'true'
    runs-on: ubuntu-latest
    timeout-minutes: 20
    steps:
      - uses: actions/checkout@v7
      - run: make test-api

  web:
    needs: changes
    if: needs.changes.outputs.web == 'true'
    runs-on: ubuntu-latest
    timeout-minutes: 20
    steps:
      - uses: actions/checkout@v7
      - run: make test-web

  ci-ok:
    if: always()
    needs: [changes, api, web]
    runs-on: ubuntu-latest
    timeout-minutes: 5
    steps:
      - name: Fail if a needed job failed or was cancelled
        if: contains(needs.*.result, 'failure') || contains(needs.*.result, 'cancelled')
        run: exit 1
```

- The filter step runs only for `pull_request`. On pushes to `main`, merge groups and manual runs it is skipped, its outputs are empty, and `|| 'true'` runs every job. A wrong filter can't skip tests after merge.
- For pull requests, dorny/paths-filter lists changed files through the API, so `changes` needs no checkout, only `pull-requests: read`. It is pinned to a commit SHA because it handles a token.
- Each filter must cover everything its job builds from: its own directory, shared packages, lockfiles, root build config and the workflow files. The `shared` anchor adds those to every filter.
- `ci-ok` runs even when other jobs fail or skip. It fails when any job it needs failed or was cancelled, and passes when they succeeded or skipped. List every job in its `needs`.
- To avoid a third-party action, check out with `fetch-depth: 2` and read `git diff --name-only HEAD^1 HEAD`. In a pull request run, `HEAD` is the test merge commit and its first parent is the base branch.

Then make `ci-ok` the only required check from this workflow. A repository admin adds it to the ruleset or branch protection once the workflow has merged, then removes the old per-job names.

If your jobs already build through Turborepo, Nx or Bazel, those tools can also select affected packages inside a job. See [affected packages](https://berrybox.io/playbooks/test-selection/affected-packages.md).

## Keep it safe

- Never put `paths` or `paths-ignore` on the `pull_request` trigger of a workflow that reports a required check. Filter at the job level instead.
- GitHub evaluates a job-level `if` before it expands a matrix. A skipped matrix job reports one check under its unexpanded name instead of one per leg, so required checks named after legs stay pending. Require `ci-ok` instead of individual legs.
- A path missing from a filter means tests silently stop running for changes that affect them. Running everything on `main` and in the merge queue catches a bad filter within one merge instead of weeks later. When unsure whether a path matters, include it.
- Swap required checks in that order. Removing the old names first opens a window where pull requests merge with nothing required. Open pull requests report `ci-ok` only after their next push or base-branch update.
- If you turn on `list-files`, the file-list outputs contain names chosen by the pull request author. Pass them to scripts through `env:`, never by interpolating `${{ }}` into a `run:` line.

## Verify

- Open a pull request that only changes a Markdown file. `changes` should finish in under a minute, `api` and `web` should show as skipped, and `ci-ok` should pass. `gh pr checks <number> --required` should list `ci-ok` as passing.
- Open one that touches `api/`. Only `api` should run, and a failing test there should turn `ci-ok` red.
- After a week, rerun the [baseline](https://berrybox.io/playbooks/baseline.md). Median runner minutes per `pull_request` run should fall, while push runs on the default branch should show the same jobs and minutes as before.

## Sources

- Flightcontrol (now Ravion): [Flightcontrol blog: gate each package's jobs on dorny/paths-filter outputs](https://www.ravion.com/blog/reduced-github-actions-bill-by-63). Monthly GitHub Actions usage fell from 46,144 minutes to 19,155, and the bill by 63%.
- OpenAI: [codex-security: skip independent jobs when a pull request only edits existing Python tests](https://github.com/openai/codex-security/pull/2002). Across seven such merged pull requests, the jobs it now skips had used 17h29m53s of aggregate runner time (139 jobs).
- OpenAI: [openai-agents-python: skip packaging jobs before runner allocation, and unroll a matrix so skipped checks keep their required names](https://github.com/openai/openai-agents-python/pull/5264)
- Sentry: [sentry-github-actions-app: require one aggregate job and drop a docs paths filter that left it pending](https://github.com/getsentry/sentry-github-actions-app/pull/146)
