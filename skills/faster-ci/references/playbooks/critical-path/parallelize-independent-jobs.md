# Start independent jobs together by dropping needs they don't use

Keep a needs edge only where the later job uses the earlier job's artifact, output or side effect, let every other job start when the run starts, and gate merges on one aggregate job.

- Playbook: [Shorten the path that ends the run](https://berrybox.io/playbooks/critical-path.md)
- Saves: wait time
- Risk: low
- Web page: https://berrybox.io/playbooks/critical-path/parallelize-independent-jobs

## Signals in your baseline

- A job on the baseline's "Most common critical path" waits for a job whose artifacts and outputs it never reads.
- A lint or format job sits in front of every test and build job through needs.
- The workflow's p50 wall time is close to the sum of the job durations on its critical path, not to its longest job.

## Why it works

GitHub starts a job only after every job in its `needs` list has finished, so each edge adds the earlier job's queue time and duration to everything behind it. Jobs run on separate machines and share nothing by default. A later job depends on an earlier one only if it downloads that job's artifact, reads its outputs, or relies on something it did outside the run, such as pushing an image tag or applying a migration. Many `needs` edges do none of that. They were added so lint would fail first, or copied from another workflow. Remove them and those jobs start together, so the run takes as long as its longest chain of real dependencies.

## Apply it

1. List the jobs on the critical path from the [baseline](https://berrybox.io/playbooks/baseline.md) report.
2. For each `needs` entry on that path, search the later job for `download-artifact`, `needs.<job>.outputs` and anything the earlier job publishes: registry tags, caches saved earlier in the same run, deployments, database changes. If you find one, keep the edge.
3. Remove the other edges. Add one aggregate job that waits for everything and make it the required check.

A common chain is lint, then test, then build, then end-to-end tests, where only the end-to-end job uses what the build produced:

```yaml
name: CI
on:
  pull_request:
  push:
    branches: [main]

permissions:
  contents: read

jobs:
  lint:
    runs-on: ubuntu-24.04
    steps:
      - uses: actions/checkout@v7
      - uses: actions/setup-node@v7
        with:
          node-version: 24
          cache: npm
      - run: npm ci
      - run: npm run lint

  test:
    runs-on: ubuntu-24.04
    steps:
      - uses: actions/checkout@v7
      - uses: actions/setup-node@v7
        with:
          node-version: 24
          cache: npm
      - run: npm ci
      - run: npm test

  build:
    runs-on: ubuntu-24.04
    steps:
      - uses: actions/checkout@v7
      - uses: actions/setup-node@v7
        with:
          node-version: 24
          cache: npm
      - run: npm ci
      - run: npm run build
      - uses: actions/upload-artifact@v7
        with:
          name: dist
          path: dist/
          retention-days: 3

  e2e:
    needs: build
    runs-on: ubuntu-24.04
    steps:
      - uses: actions/checkout@v7
      - uses: actions/setup-node@v7
        with:
          node-version: 24
          cache: npm
      - run: npm ci
      - uses: actions/download-artifact@v8
        with:
          name: dist
          path: dist/
      - run: npm run test:e2e

  ci-ok:
    if: always()
    needs: [lint, test, build, e2e]
    runs-on: ubuntu-24.04
    steps:
      - name: Fail if any job failed or was cancelled
        if: contains(needs.*.result, 'failure') || contains(needs.*.result, 'cancelled')
        run: exit 1
```

- `lint`, `test` and `build` have no `needs`, so all three start when the run starts.
- `e2e` keeps `needs: build` because it downloads `dist`. That edge is a real dependency.
- `ci-ok` is the job to mark as required. `if: always()` makes it run even when a job it needs fails. Without it, GitHub skips the gate after a failure, and a skipped required check may not block the merge.
- The gate fails on `failure` and `cancelled` but accepts `skipped`, so a job you skip on purpose with a job-level `if` doesn't block the merge.

If lint fails often and one job is expensive, keeping a sub-minute lint job in front of that one job is a fair trade. The edges worth removing are the ones where a long job waits for another long job.

## Keep it safe

- Look for side effects outside artifacts before you remove an edge: an image pushed under the commit SHA, a cache the earlier job saved, a migration, a preview deploy.
- Never remove the `needs` that hold deploy, release or publish jobs behind your checks. The same goes for security gates, such as a job that checks the author's permissions or an approval environment in front of jobs that receive secrets.
- Job names don't change, so existing required checks keep matching. Add `ci-ok` to the ruleset or branch protection, and remove the old required checks only after it has reported on a few pull requests.
- Once lint stops gating, a pull request with a lint error still runs every other job, which costs minutes on failing runs.
- Jobs that used to run one after another may now use the same staging database, test account or rate-limited API at the same time. Give each job its own resource or keep that edge.

## Verify

- Run the baseline for your branch. The **Most common critical path** should list fewer jobs, and p50 wall time should drop by about the duration of the jobs you took off the path.
- **Runner min/run (p50)** should stay about the same on green runs. Check failing runs too if lint no longer gates.
- Confirm with `gh pr checks` that every job still reports, then push a commit with a lint error and watch `ci-ok` fail.

## Sources

- Deutsche Telekom: [BOOTy: start the build and the ISO check after lint instead of after the test and E2E jobs](https://github.com/telekom/BOOTy/pull/883)
- Uber: [Uber Engineering: run the independent dependency-resolution check in parallel in the Go monorepo pipeline](https://www.uber.com/us/en/blog/how-we-halved-go-monorepo-ci-build-time/)
- Shopify: [tecnix: start the test jobs without waiting for the aggregate basic-checks job](https://github.com/Shopify/tecnix/pull/74)
- Bun: [bun: run eight source-lint tests in their own workflow instead of behind the full build](https://github.com/oven-sh/bun/pull/34682)
