# Select the tests each change needs, and keep a full-suite backstop

On pull requests, run only the tests that depend on what a change touched, fall back to the full suite when shared inputs change, and keep running everything in the merge queue, on the default branch and nightly.

- Playbook: [Run only what a change can affect](https://berrybox.io/playbooks/test-selection.md)
- Saves: wait time and runner minutes
- Risk: high
- Web page: https://berrybox.io/playbooks/test-selection/affected-tests

## Signals in your baseline

- The test job is the long pole on every pull request, and its duration barely changes with the size of the diff.
- Most merged pull requests touch a few files in one area (check `gh pr list --state merged --json files`), but every run executes the whole suite.
- Workflows already run on `push` to the default branch or on `merge_group`, where a full run can catch what selection misses.

## Why it works

Most changes can only break the tests that exercise the code they touched. If you know which tests depend on which files, a pull request that edits one module needs that module's tests, not the whole suite. Tools learn that mapping in one of two ways: from the import graph (Vitest's `--changed`, Jest's `--changedSince`), or from recording what each test actually executed or opened on earlier runs (pytest-testmon, Stripe's file-access tracing).

No mapping is perfect. Files read at runtime, configuration and shared setup slip past it. So selection only decides what runs before merge. The merge queue, the default branch and a nightly run still execute everything and catch what selection missed.

## Apply it

### Node with Vitest or Jest

```yaml
name: test
on:
  pull_request:
  merge_group:
  push:
    branches: [main]
  schedule:
    - cron: "17 3 * * *"
  workflow_dispatch:

permissions:
  contents: read

jobs:
  test:
    runs-on: ubuntu-latest
    timeout-minutes: 30
    steps:
      - uses: actions/checkout@v7
        with:
          fetch-depth: 2
      - uses: actions/setup-node@v7
        with:
          node-version: 24
          cache: npm
      - run: npm ci
      - id: scope
        run: |
          scope=full
          if [ "$GITHUB_EVENT_NAME" = pull_request ] && changed=$(git diff --name-only HEAD^1 HEAD); then
            if ! grep -qE '(^|/)(package\.json|package-lock\.json|pnpm-lock\.yaml|yarn\.lock|tsconfig[^/]*\.json|vite(st)?\.config\.[a-z]+)$|^\.github/|^test/(setup|fixtures)/' <<< "$changed"; then
              scope=affected
            fi
          fi
          echo "scope=$scope" >> "$GITHUB_OUTPUT"
          echo "Test scope: $scope" >> "$GITHUB_STEP_SUMMARY"
      - if: steps.scope.outputs.scope == 'affected'
        run: npx vitest run --changed HEAD^1 --passWithNoTests
      - if: steps.scope.outputs.scope == 'full'
        run: npx vitest run
```

- Only `pull_request` runs select. The merge queue, pushes to `main`, the nightly schedule and manual runs always get `full`.
- On `pull_request`, the checkout is GitHub's merge commit, so `HEAD^1` is the base branch and `fetch-depth: 2` is enough to diff against it.
- The `grep` list is the fallback: lockfiles, manifests, TypeScript and Vitest config, CI files and shared test setup run the full suite. Adjust the last pattern to your repository. If `git diff` fails, the scope stays `full`.
- Vitest's own `forceRerunTriggers` (by default `package.json` and the Vite and Vitest configs) also forces a full run under `--changed`. Add runtime-read paths, such as JSON fixtures, to it.
- With Jest, use `npx jest --changedSince=HEAD^1 --passWithNoTests`.

### Python with pytest-testmon

pytest-testmon records which code each test executed and stores it in `.testmondata`. In the same job, after the scope step, restore the data the default branch saved and let testmon pick the tests:

```yaml
      - uses: actions/cache/restore@v6
        with:
          path: .testmondata
          key: testmon-${{ runner.os }}-${{ github.sha }}
          restore-keys: testmon-${{ runner.os }}-
      - if: steps.scope.outputs.scope == 'affected'
        run: pytest --testmon
      - if: steps.scope.outputs.scope == 'full'
        run: pytest --testmon-noselect
      - if: github.ref == 'refs/heads/main'
        uses: actions/cache/save@v6
        with:
          path: .testmondata
          key: testmon-${{ runner.os }}-${{ github.sha }}
```

`--testmon-noselect` runs everything and refreshes the data. Without restored data, `--testmon` runs every test. Add `requirements*.txt`, `uv.lock`, `poetry.lock`, `pyproject.toml` and `conftest.py` to the fallback list. testmon stops collecting under coverage, so don't run the main-branch job with `--cov`.

## Keep it safe

- **Keep the net.** Run everything on `merge_group`, on pushes to the default branch and nightly, as the workflow does. With a [merge queue](https://berrybox.io/playbooks/pr-volume/merge-queue.md), nothing merges without a full run. Shopify runs the full suite on every deploy. When a full run fails on something selection skipped, add the pattern that missed to the fallback list.
- **Fall back on shared inputs.** Stripe forces every test to run when files loaded before any test change, and always runs tests that discover files by globbing, since a new file has no recorded reads.
- **Watch runtime reads.** Import graphs miss fixtures, templates, snapshots and config read at runtime. Put those paths in the fallback list.
- **Keep the data fresh.** Recorded maps go stale. When Anthropic's result listener fell behind, new and fixed tests didn't run until it caught up. Refresh the data on every default-branch run.
- **Required checks.** Select inside the job. A trigger-level `paths` filter would leave a required check pending forever. A selected run with zero tests passes, which is safe only because the net runs everything later.
- **Trust.** Run selection on `pull_request`, never `pull_request_target`. Pull request runs only read the default branch's testmon data and can't overwrite it.
- **Flaky tests.** Fewer tests per pull request moves flaky failures to the full runs. Track them with [flaky tests](https://berrybox.io/playbooks/flaky-tests.md).

## Verify

- Compare the test step's p50 on pull requests with the [baseline](https://berrybox.io/playbooks/baseline.md), and count how many runs chose `affected` from the step summary.
- Full runs on the merge queue, `main` and the nightly schedule report the same test count as the baseline and stay green.
- Track misses: every full-run failure that a pull request run didn't catch. Each one should add a fallback rule.

## Sources

- Stripe: [Stripe blog: select tests by the files each one opened in earlier runs, with special cases that force wider runs](https://stripe.dev/blog/selective-test-execution-at-stripe-fast-ci-for-a-50m-line-ruby-monorepo). On average Stripe runs roughly 5% of its Ruby test suite per build (median 0.5%), using under 10% of the compute of running everything.
- Meta: [Meta engineering: predict which dependent tests can fail, using a model trained on past changes and test outcomes](https://engineering.fb.com/2018/11/21/developer-tools/predictive-test-selection/). Caught more than 99.9 percent of regressions before they were visible in trunk, while running a third of the tests that transitively depend on the modified code.
- Shopify: [Shopify engineering: select tests from a call-graph map rebuilt on main, and run the full suite on every deploy](https://shopify.engineering/spark-joy-by-running-fewer-tests). About 25% less compute time, with 99.94% recall: five failing tests missed across 8,360 merged commits.
- Anthropic: [Anthropic: pick tests per pull request from package relevance and recorded results, and keep that history current](https://claude.com/resources/articles/agentic-coding-is-straining-ci-heres-how-we-scaled-test-impact-analysis-at-anthropic)
