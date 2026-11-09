# Combine short checks whose setup takes longer than the work

Run lint, format, type and other short checks as steps of one job that checks out and installs once, so each check stops paying for its own runner, setup and rounded-up minute.

- Playbook: [Shorten the path that ends the run](https://berrybox.io/playbooks/critical-path.md)
- Saves: runner minutes
- Risk: low
- Web page: https://berrybox.io/playbooks/critical-path/merge-tiny-jobs

## Signals in your baseline

- The workflow has several jobs whose only work is one short command, such as lint, a format check, a type check or a license check, after the same checkout and install steps.
- The workflow's "Runner min/run (p50)" is several times its "p50 wall", because many short jobs each bill at least a minute.
- In the job logs, checkout, toolchain setup and dependency install take longer than the check itself.

## Why it works

Every job starts on a fresh runner. Before a 10-second lint command can run, the job waits for a machine, checks out the repository, installs a toolchain and restores dependencies. GitHub-hosted runners also round each job's time up to the next whole minute, so ten 20-second checks bill ten minutes. Run those checks as steps of one job and the queue, checkout and install happen once.

Merging is the reverse of [splitting the long pole](https://berrybox.io/playbooks/critical-path/split-the-long-pole.md), and the same arithmetic decides between them. Merge when setup is most of each job's time and the merged job still finishes before the long pole. Split when the work you would move is much longer than a setup and sits on the critical path. If the merged job becomes the new long pole, you've traded wall time for minutes: run its checks in parallel, or split the slowest one out again.

## Apply it

1. List the jobs that take under about two minutes and share the same runner type and setup.
2. Move their commands into one job, after a single checkout and install.
3. Run the checks as a `parallel` group, so each one runs to completion and keeps its own log even when another fails.

```yaml
jobs:
  checks:
    runs-on: ubuntu-24.04
    permissions:
      contents: read
    steps:
      - uses: actions/checkout@v7
      - uses: pnpm/action-setup@v6
      - uses: actions/setup-node@v7
        with:
          node-version: 24
          cache: pnpm
      - run: pnpm install --frozen-lockfile
      - parallel:
          - name: Lint
            run: pnpm run lint
          - name: Format
            run: pnpm run format:check
          - name: Types
            run: pnpm run typecheck
          - name: License headers
            run: pnpm run check:licenses
```

- `parallel` starts the four checks together and waits for all of them. If one fails, the job fails, but the other checks still run to the end, so a single push shows every problem.
- `pnpm/action-setup` reads the pnpm version from the `packageManager` field in `package.json`.
- Steps in a `parallel` group run as background steps, and a job runs at most 10 of those at once.
- On self-hosted runners whose version predates `parallel` (added in June 2026), list the checks as ordinary steps. Give the install step `id: install` and every check after the first `if: ${{ !cancelled() && steps.install.outcome == 'success' }}`, so a failing lint step doesn't stop the type check.

## Keep it safe

- Update required checks in the same change. If `lint`, `format` and `typecheck` were required, new pull requests will wait forever for checks that no longer report. Replace them with `checks` in the ruleset or branch protection when the change merges.
- Merge only jobs that run on the same runner and need the same access. A job that needs `pull-requests: write`, a deploy key or other secrets should stay separate from jobs that run code from the pull request, so the merged job can keep `contents: read`.
- Look for hidden dependencies between checks. Each job used to start from a clean checkout, and now a check may see files that another step generated or changed, such as codegen output that the format check rejects. Run code generation before the checks and catch unexpected changes with `git diff --exit-code`.
- Watch CPU and memory. Four checks at once on a 2-core runner compete for it. If the merged job gets slow, run the heavy checks in sequence.

## Verify

- In the branch baseline, **Runner min/run (p50)** should fall by at least one minute for each job you removed, plus the setup time it repeated.
- p50 wall shouldn't rise. If the merged job turns up as the **Long-pole job**, move a check back out or give the job more cores.
- Break each check in a scratch commit and confirm that the merged job fails with that step marked while the other checks still report.

## Sources

- Linear: [Linear Now: consolidate seven short checks into two jobs that run the tasks concurrently](https://linear.app/now/ci-bottleneck-reworked#batch-short-checks-into-fewer-jobs). Based on June usage, the change saved roughly 87,000 runner-minutes per month, equivalent to 11.8% of Linear's total CI usage.
- Canva: [Canva Engineering: group the steps of the backend and ML pipeline](https://www.canva.dev/blog/engineering/faster-ci-builds-at-canva/). Average build times fell from 49 minutes to 35, and the pipeline went from 45 to 16 steps, with build minutes down by around 50%.
- Stripe: [stripe-ios: combine similar small CI jobs](https://github.com/stripe/stripe-ios/pull/6969)
- Bun: [bun: compile the C++ objects in the same step as the Rust build instead of on a separate agent](https://github.com/oven-sh/bun/pull/37733). Build agents per build went from 26 to 13, and agent-minutes from about 93 to about 69.
