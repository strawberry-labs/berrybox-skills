# Run CI once per commit instead of on both push and pull_request

A workflow that triggers on every push and on pull_request runs each pull request commit twice. Limit push to the default branch so each commit gets one run.

- Playbook: [Stop paying for runs nobody needs](https://berrybox.io/playbooks/wasted-runs.md)
- Saves: runner minutes
- Risk: low
- Web page: https://berrybox.io/playbooks/wasted-runs/one-run-per-commit

## Signals in your baseline

- The workflow's on block lists push with no branches filter next to pull_request, for example on: [push, pull_request].
- The baseline has push and pull_request rows for the same workflow with similar run counts.
- `gh run list --commit <sha>` shows two runs of one workflow for the same commit, started seconds apart.

## Why it works

`push` fires for every branch that receives a commit. When that branch has an open pull request, `pull_request` fires again for the same commit. The two runs install the same dependencies and run the same tests: the push run tests the branch head, and the pull request run tests the merge of that head into the base branch. You pay for both, and they start together, so they also compete for runners and for shared downloads. Two runs hitting the same package mirror at the same moment can produce a failure that neither would hit alone.

Keep the pull request run. It tests what will actually merge, and it is the only one of the two that runs for pull requests from forks. Keep push runs only where nothing else covers the commit: the default branch after a merge, release branches and tags.

## Apply it

Limit `push` to the branches that need post-merge runs. This is the default fix:

```yaml
on:
  push:
    branches: [main]
  pull_request:
  workflow_dispatch:
```

- Replace `main` with your default branch. Add release branches (`'release/**'`) or a `tags:` pattern if jobs in this workflow build releases from them.
- `pull_request` with no filter still runs once for every pull request commit.
- `workflow_dispatch` lets someone run the workflow by hand on a branch that has no pull request yet. Checks from manual runs don't count toward a pull request's required checks, which is fine for exploratory runs.

Change only workflows that listen to both events. A workflow that runs on `push` alone may be where your required checks come from.

Some projects also want CI on pushes to contributors' forks before a pull request exists. Only those projects need the job-level variant. It keeps both triggers and skips pushes to this repository's own branches in the first job, since jobs that `need` a skipped job are skipped too. Each skipped push run still adds checks to the commit, so the variant also renames its push-side jobs:

```yaml
on: [push, pull_request]

jobs:
  test:
    name: ${{ github.event_name == 'push' && 'test (push)' || 'test' }}
    # Runs for pull requests, for pushes to forks and for pushes to main.
    # Other pushes to this repository skip: their pull request run covers them.
    if: >-
      github.event_name == 'pull_request' ||
      github.repository != 'OWNER/REPO' ||
      github.ref == 'refs/heads/main'
    runs-on: ubuntu-latest
    timeout-minutes: 20
    steps:
      - uses: actions/checkout@v7
      - run: make test
```

- Replace `OWNER/REPO` with this repository. In a fork, `github.repository` holds the fork's name, so pushes there still run.
- The `name:` expression gives push runs a different check name, so a skipped push run can't report a passing `test` on the commit the pull request is testing. Put it on every job that reports a required check, since jobs downstream of `test` are skipped along with it and report under their own names. Keep the pull request side identical to the job's current check name, or branch protection waits for a check that no longer reports.

## Keep it safe

- Before you narrow `push`, check that every workflow reporting a required check also triggers on `pull_request`. A required check that only came from push runs stops reporting on pull requests and blocks every merge.
- Search the workflow for jobs gated on `github.event_name == 'push'`, such as preview deploys or branch artifacts. Narrowing `push` silently turns those off for feature branches.
- Leave the default-branch push run in place. It refreshes caches that every branch can restore (pull request caches are visible only to that pull request), and it records the result of each merged commit.
- The job-level variant can let a pull request merge without its real check passing. A skipped job reports success, and the skipped push run puts its checks on the same commit as the pull request run. If one of those checks has a required check's name, it can satisfy the requirement while the pull request run fails, and GitHub doesn't document which of two same-named checks branch protection uses. Use the variant only in workflows that report no required checks, or keep the `name:` line on every required job.
- Concurrency groups keyed on the pull request number (see [cancel stale runs](https://berrybox.io/playbooks/wasted-runs/cancel-stale-runs.md)) keep working, because push runs on `main` fall back to `github.ref`.

## Verify

- Push a commit to a branch with an open pull request. With the branches filter, `gh run list --commit <sha>` should show one run of the workflow, from `pull_request`. With the job-level variant you'll also see a push run whose jobs were all skipped without a runner.
- Confirm the required checks still report on that pull request: `gh pr checks <number> --required`.
- After a week, rerun the [baseline](https://berrybox.io/playbooks/baseline.md). The `push` row for the workflow should drop to roughly the number of merges to the default branch, and runner minutes per merged pull request should fall by about the share the push runs used to take. Wall time per run shouldn't change.

## Sources

- Shopify: [vscode-shopify-ruby: limit push runs to main so branch commits run CI once](https://github.com/Shopify/vscode-shopify-ruby/pull/808)
- Spotify: [target-determinator: run push presubmits only on main to stop duplicate Bazel matrices](https://github.com/spotify/target-determinator/pull/15)
- Moto: [moto: skip in-repository branch pushes in the root job, keep CI for pushes to forks](https://github.com/getmoto/moto/pull/10525)
