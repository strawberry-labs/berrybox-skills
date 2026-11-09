# Build and test only the affected packages in a monorepo

Let the workspace tool map a change to the packages it touches and every package that depends on them, run tasks for that set only, and run everything when root config, lockfiles or CI files change.

- Playbook: [Run only what a change can affect](https://berrybox.io/playbooks/test-selection.md)
- Saves: wait time and runner minutes
- Risk: medium
- Web page: https://berrybox.io/playbooks/test-selection/affected-packages

## Signals in your baseline

- A Turborepo, Nx, pnpm workspace, Gradle multi-project or Bazel repository runs every package's lint, test and build on every pull request.
- Most pull requests touch one or two packages, but the build and test jobs take as long as when every package changes.
- The workflows contain no `--affected`, `nx affected`, `--filter=...[<ref>]`, bazel-diff or similar package selection.

## Why it works

A monorepo already records how its packages depend on each other. Given the files a change touched, the workspace tool finds the packages that own them, adds every package that depends on those, and runs tasks for that set alone. A change to a leaf package then runs one package's checks instead of all of them, while a change to a shared library still reaches everything that uses it.

The graph only covers what packages declare. Files that belong to no package, such as the lockfile, root config and CI files, can change every package's behavior, so a change to them has to run everything.

## Apply it

### Turborepo

```yaml
name: ci
on:
  pull_request:
  merge_group:
  push:
    branches: [main]

permissions:
  contents: read

jobs:
  check:
    runs-on: ubuntu-latest
    timeout-minutes: 30
    steps:
      - uses: actions/checkout@v7
        with:
          fetch-depth: 0
          filter: blob:none
      - uses: pnpm/action-setup@v6
      - uses: actions/setup-node@v7
        with:
          node-version: 24
          cache: pnpm
      - run: pnpm install --frozen-lockfile
      - id: scope
        env:
          BASE_SHA: ${{ github.event.pull_request.base.sha }}
        run: |
          scope=full
          if [ "$GITHUB_EVENT_NAME" = pull_request ] && changed=$(git diff --name-only "$BASE_SHA" HEAD); then
            if ! grep -qE '^(package\.json|pnpm-lock\.yaml|pnpm-workspace\.yaml|turbo\.json|tsconfig[^/]*\.json)$|^(\.github|scripts)/' <<< "$changed"; then
              scope=affected
            fi
          fi
          echo "scope=$scope" >> "$GITHUB_OUTPUT"
          echo "Package scope: $scope" >> "$GITHUB_STEP_SUMMARY"
      - if: steps.scope.outputs.scope == 'affected'
        env:
          TURBO_SCM_BASE: ${{ github.event.pull_request.base.sha }}
        run: pnpm turbo run lint test build --affected
      - if: steps.scope.outputs.scope == 'full'
        run: pnpm turbo run lint test build
```

- `--affected` runs tasks for packages changed since `TURBO_SCM_BASE` (the pull request's base commit here) and for every package that depends on them.
- `fetch-depth: 0` with `filter: blob:none` fetches the history Turborepo needs without file contents. If the history is missing, Turborepo treats every package as changed.
- Root files, the lockfile and CI files force a full run, and so does every event other than `pull_request`. Adjust the pattern to your layout.
- `pnpm/action-setup` reads the pnpm version from `packageManager` in `package.json`.

### Nx

Add `actions: read` to the job's permissions, keep the same checkout, and replace the two Turborepo steps:

```yaml
      - if: steps.scope.outputs.scope == 'affected'
        uses: nrwl/nx-set-shas@e602fada7ad5987b0f7b1905e7a99ea1c661514c # v5.1.0
      - if: steps.scope.outputs.scope == 'affected'
        run: npx nx affected -t lint test build
      - if: steps.scope.outputs.scope == 'full'
        run: npx nx run-many -t lint test build
```

`nx-set-shas` sets `NX_BASE` and `NX_HEAD`, which `nx affected` reads. List files every project depends on, such as CI config, under `sharedGlobals` in `nx.json`, as Grafana did.

### Other workspaces

- pnpm without a task runner: `pnpm --filter "...[origin/main]" test` runs `test` in packages changed since `origin/main` and in their dependents.
- Gradle has no built-in selection. Dropbox computed affected modules from the module graph and skipped `Test` tasks for the rest with `onlyIf`.
- Bazel: `bazel-diff` lists the targets whose inputs differ between two commits. Test those.

If you fan out one job per package with a dynamic matrix, the set of check names changes from run to run. Require a single aggregate job instead, the way Supabase added a `CI passed` job:

```yaml
  ci-passed:
    if: always()
    needs: [test]
    runs-on: ubuntu-latest
    steps:
      - if: contains(needs.*.result, 'failure') || contains(needs.*.result, 'cancelled')
        run: exit 1
```

Skip the matrix job with `if:` when the package list is empty: a skipped dependency doesn't fail the aggregate, and an empty matrix would fail the run.

## Keep it safe

- **Shared inputs run everything.** Lockfiles, the root manifest, workspace and task-runner config, shared `tsconfig` files, CI files and root scripts belong to no package. Shopify's change keeps schemas, generators and tooling running every platform.
- **Declare real dependencies.** A package that imports an unlisted sibling, reads another package's files at runtime or runs a root script won't be marked affected. Grafana found a lint input pointing at a missing file, which would have let config changes skip checks. Declare the dependency, or add the path to the fallback list.
- **Fail closed.** If the tool can't compute the set, run everything.
- **Required checks.** Select inside a job that always reports, or require an aggregate job. Never filter with trigger-level `paths`; see [skip unchanged paths](https://berrybox.io/playbooks/wasted-runs/skip-unchanged-paths.md) for job-level patterns.
- **Keep the net.** Run everything on `merge_group`, on pushes to the default branch or nightly. Supabase tests everything on `main` and on manual runs.
- **Core changes fan out.** A change to a widely used package still selects most of the repository. Dropbox's selective job passed 90 minutes when a core module changed, so pair this with [sharding](https://berrybox.io/playbooks/slow-tests/shard-tests.md).

## Verify

- Turborepo prints `Packages in scope` at the start of a run. On a one-package pull request it should list that package and its dependents.
- Compare the check job's p50 on pull requests with the [baseline](https://berrybox.io/playbooks/baseline.md), and look at the largest runs separately.
- Confirm a pull request that only touches the lockfile ran everything, and that full runs on `main` report the same number of tests as before.

## Sources

- Grafana Labs: [plugin-tools: gate jobs on `nx show projects --affected` and make shared files affect every package](https://github.com/grafana/plugin-tools/pull/3078)
- Supabase: [supabase-py: test a changed package and its dependents on pull requests, everything on main, behind one required job](https://github.com/supabase/supabase-py/pull/1967)
- Shopify: [checkout-kit: run protocol checks only for the affected language binding, and every platform when shared inputs change](https://github.com/Shopify/checkout-kit/pull/546)
- Dropbox: [Dropbox blog: build and test only the Android modules a change affects](https://dropbox.tech/mobile/revamping-the-android-testing-pipeline-at-dropbox). Run as a shadow job, the selective pipeline averaged about 35 minutes, against 75 minutes for the existing job.
