# Install only the packages and tools each job uses

Scope each job's install to the workspace packages and dependency groups it actually runs, and skip the full install in jobs that only need one small tool.

- Playbook: [Get setup off the clock](https://berrybox.io/playbooks/slow-setup.md)
- Saves: wait time and runner minutes
- Risk: medium
- Web page: https://berrybox.io/playbooks/slow-setup/install-only-what-runs

## Signals in your baseline

- Jobs that lint, type-check or test one package run a full workspace install (pnpm install, npm ci, uv sync) at the repository root.
- The install step takes about the same time in every job, whether the job runs one script or the whole suite.
- Change-detection or metadata gate jobs install the full dependency tree before running a single tool.
- Jobs install browsers, system packages or language toolchains that none of their commands call.

## Why it works

Install time grows with the number of packages, and a workspace-wide install pulls in every package's dependencies: the web app's bundler, the mobile app's toolchain, the docs site's generator. A job that tests the API uses a fraction of that. Package managers can install a subset: pnpm takes a filter, Yarn can focus on one workspace, and uv and Poetry install named dependency groups. A job that runs a single CLI, such as a change detector or a formatter, can install that one tool in a second or two instead of the whole tree.

The same goes for system packages and runtimes. Stripe's Android CI installed Ruby, about two minutes of work, for every type of check, though only a few used it.

## Apply it

For each job, list what its `run:` steps actually execute and which packages those commands touch. Then cut the install to match.

### pnpm workspaces

```yaml
jobs:
  api-tests:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7
      - uses: pnpm/action-setup@v6
      - uses: actions/setup-node@v7
        with:
          node-version: 24
          cache: pnpm
      - run: pnpm install --frozen-lockfile --filter "@acme/api..."
      - run: pnpm --filter "@acme/api" test
```

- `@acme/api...` selects the package and every workspace package it depends on, directly or not, and installs their dependencies only.
- `--frozen-lockfile` still refuses to change the lockfile, so the job gets the same versions a full install would.
- With Yarn 4, `yarn workspaces focus @acme/api` does the same job.

### Python with uv or Poetry

```yaml
- run: uv sync --locked --only-group lint
- run: uv run --no-sync ruff check .
```

- `--only-group lint` installs that group without the project or the default `dev` group.
- `--no-sync` stops `uv run` from syncing the rest of the project back in before it runs the command.
- Poetry has the same idea: `poetry install --only lint --no-root`.

### Jobs that need one tool

A gate that only asks Turborepo which packages changed doesn't need `node_modules`; Mastra replaced a full install of about 60 seconds with a global turbo install of about 2. Install the tool by itself, at the same version the lockfile pins, or use the tool's own action. For browser tests, install only the browsers you run (`npx playwright install --with-deps chromium`) rather than all of them.

For the same idea at the level of jobs and test suites, see [affected packages](https://berrybox.io/playbooks/test-selection/affected-packages.md).

## Keep it safe

- **Missing dependencies.** Most show up as loud failures ("Cannot find module", "command not found"), which you fix by widening the filter. The quiet case is a test that skips itself when an import is missing, such as `pytest.importorskip`. Compare test counts, not just pass or fail.
- **Root tools.** A filtered install may leave out tools declared only in the workspace root's `package.json`. If the job calls one, declare it in the package that uses it or widen the filter.
- **Tool versions.** A tool installed outside the lockfile can drift from the version developers run. Pin it to the lockfile's version, and update both together.
- **Shared caches.** If a filtered job saves the dependency cache under the same key a full-install job uses, it can save a partial package store that the full job then restores and tops up on every run. Let one full-install job on the default branch save that key, and have filtered jobs restore only (see [drop slow caches](https://berrybox.io/playbooks/slow-setup/drop-slow-caches.md)).
- **Required checks and security.** Job names and triggers don't change. If you add a third-party action to install a tool, pin it to a release, or to a full commit SHA if the job has secrets or write permissions.

## Verify

- Compare the install step's p50 in each changed job with the [baseline](https://berrybox.io/playbooks/baseline.md), and the job's total duration.
- Confirm each job ran the same number of tests or checked the same files as before, and that the same checks reported.
- Watch the next lockfile update: filtered jobs should still pass with `--frozen-lockfile`.

## Sources

- Linear: [Linear blog: restrict the API test workflow's pnpm install to the API package](https://linear.app/now/ci-bottleneck-reworked#install-only-the-dependencies-each-job-needs). Restricting the install to the API package cut pnpm install from 44-73 seconds to 16-18 seconds.
- Mastra: [mastra: skip pnpm install in change-detection jobs and install only turbo](https://github.com/mastra-ai/mastra/pull/12246)
- Stripe: [stripe-android: install Ruby only in the CI workflows that use it](https://github.com/stripe/stripe-android/pull/10184)
