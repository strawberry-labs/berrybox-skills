# Balance shards by recorded test timings

Assign tests to shards by how long they took on the default branch instead of by count, give every shard the same timings file and refresh it after each merge so no shard trails the others.

- Playbook: [Make the test suite finish sooner](https://berrybox.io/playbooks/slow-tests.md)
- Saves: wait time
- Risk: medium
- Web page: https://berrybox.io/playbooks/slow-tests/balance-shards

## Signals in your baseline

- In the Slowest jobs table, the slowest shard of a sharded test job has a p50 at least 1.5 times the fastest shard's.
- The same shard index is the slowest in most runs.
- Shards are split by count (--shard in Jest, Vitest or Playwright, or pytest-split with no durations file), and a few test files run far longer than the rest.

## Why it works

A sharded job ends when its slowest shard ends. Jest and Vitest hand each shard the same number of files, picked by a hash of the path. Playwright hands out equal numbers of files, or of tests with `fullyParallel`. pytest-split without timings hands out equal numbers of tests. None of them looks at duration, so one shard can draw the three slowest files and run twice as long as the others while they sit idle.

Recorded timings fix the split. Sort the tests longest first and give each to the shard with the smallest total so far, and the shards finish close together. pytest-split does this with `--splitting-algorithm least_duration`; Jest and Vitest let you replace their `shard()` method. The same imbalance shows up between workers inside one job, which is what Ramp fixed for pytest-xdist.

Two limits stay. Jest and Vitest move whole files, so a file that takes longer than the total ÷ N sets the floor until you split it. And every shard must compute its split from the same timings file. If two shards read different versions, one test can run twice while another runs nowhere.

## Apply it

Measure the spread first. Run this for three to five recent runs:

```bash
gh run view RUN_ID --json jobs --jq '.jobs[] | select(.name | startswith("test (")) | [.name, ((.completedAt | fromdateiso8601) - (.startedAt | fromdateiso8601))] | @tsv'
```

If the slowest shard leads by less than about 15%, stop here. Otherwise split the files that run longer than the total ÷ N, then add timings.

### pytest

```yaml
jobs:
  timings:
    runs-on: ubuntu-latest
    timeout-minutes: 5
    outputs:
      key: ${{ steps.lookup.outputs.cache-matched-key }}
    steps:
      - id: lookup
        uses: actions/cache/restore@v6
        with:
          path: test-durations.json
          key: test-durations-${{ github.run_id }}
          restore-keys: test-durations-
          lookup-only: true

  test-shard:
    needs: timings
    name: test (${{ matrix.shard }}/${{ strategy.job-total }})
    runs-on: ubuntu-latest
    timeout-minutes: 20
    strategy:
      fail-fast: false
      matrix:
        shard: [1, 2, 3, 4]
    steps:
      - uses: actions/checkout@v7
      - uses: actions/setup-python@v7
        with:
          python-version: "3.13"
          cache: pip
      - run: pip install -r requirements-dev.txt pytest-split
      - if: ${{ needs.timings.outputs.key != '' }}
        uses: actions/cache/restore@v6
        with:
          path: test-durations.json
          key: ${{ needs.timings.outputs.key }}
          fail-on-cache-miss: true
      - name: Run shard
        run: |
          pytest --splits ${{ strategy.job-total }} --group ${{ matrix.shard }} \
            --splitting-algorithm least_duration \
            --durations-path test-durations.json --store-durations --clean-durations \
            --junitxml=reports/junit-${{ matrix.shard }}.xml
          mv test-durations.json reports/durations-${{ matrix.shard }}.json
      - if: ${{ !cancelled() }}
        uses: actions/upload-artifact@v7
        with:
          name: junit-shard-${{ matrix.shard }}
          path: reports/
          retention-days: 7
          overwrite: true

  save-timings:
    needs: test-shard
    if: ${{ github.event_name == 'push' && github.ref_name == github.event.repository.default_branch }}
    runs-on: ubuntu-latest
    timeout-minutes: 5
    steps:
      - uses: actions/download-artifact@v8
        with:
          pattern: junit-shard-*
          path: reports
          merge-multiple: true
      - run: jq -s 'add' reports/durations-*.json > test-durations.json
      - uses: actions/cache/save@v6
        with:
          path: test-durations.json
          key: test-durations-${{ github.run_id }}-${{ github.run_attempt }}
```

- The `timings` job looks up the newest saved timings without downloading them and passes the exact key on. Every shard restores that one entry, so a save that lands mid-run can't give shards different splits. If the shards already need a build job, do the lookup there.
- With no saved timings yet, the restore is skipped and pytest-split splits by count.
- `--clean-durations` makes each shard write only the tests it ran, so `jq -s 'add'` joins the shard files into one complete set.
- `save-timings` runs only on default-branch pushes where every shard passed (a job without a status function in `if` requires its `needs` to succeed). Keep the aggregate `test` job from [Shard tests](https://berrybox.io/playbooks/slow-tests/shard-tests.md) as the required check.

The simpler alternative is pytest-split's default workflow: commit the durations file and refresh it by hand when the split drifts. Every shard reads the same commit.

### Vitest or Jest

Replace the sequencer's `shard()` and register it with `test: { sequence: { sequencer: TimingSequencer } }` in `vitest.config.ts`:

```ts
import { existsSync, readFileSync } from 'node:fs'
import { relative } from 'node:path'
import { BaseSequencer, type TestSpecification } from 'vitest/node'

const timings: Record<string, number> = existsSync('test-durations.json')
  ? JSON.parse(readFileSync('test-durations.json', 'utf8'))
  : {}

export class TimingSequencer extends BaseSequencer {
  async shard(files: TestSpecification[]): Promise<TestSpecification[]> {
    const { index, count } = this.ctx.config.shard!
    const known = Object.values(timings)
    const average = known.length ? known.reduce((a, b) => a + b, 0) / known.length : 1
    const weighted = files
      .map((spec) => {
        const path = relative(this.ctx.config.root, spec.moduleId)
        return { spec, id: `${spec.project.name} ${path}`, seconds: timings[path] ?? average }
      })
      .sort((a, b) => b.seconds - a.seconds || (a.id < b.id ? -1 : 1))
    const totals = new Array<number>(count).fill(0)
    const mine: TestSpecification[] = []
    for (const { spec, seconds } of weighted) {
      const target = totals.indexOf(Math.min(...totals))
      totals[target] += seconds
      if (target === index - 1) mine.push(spec)
    }
    return mine
  }
}
```

Use the same workflow as above, minus the pytest flags. In `save-timings`, build the file from the shards' JUnit reports, where each `<testsuite>` is one file named by its path from the project root:

```bash
python3 - <<'EOF'
import glob, json, xml.etree.ElementTree as ET
timings = {}
for path in glob.glob("reports/junit-*.xml"):
    for suite in ET.parse(path).getroot().iter("testsuite"):
        timings[suite.get("name")] = float(suite.get("time"))
json.dump(timings, open("test-durations.json", "w"), indent=1, sort_keys=True)
EOF
```

Jest works the same way: extend `@jest/test-sequencer`, override `shard(tests, { shardIndex, shardCount })`, key on `path.relative(rootDir, test.path)` and set `JEST_JUNIT_SUITE_NAME: "{filepath}"`.

### Playwright

Playwright has no public option for timing-based sharding. Set `fullyParallel: true` so it balances individual tests instead of files, and split spec files whose tests must run in order.

## Keep it safe

- Never restore timings in the shards with `restore-keys`. Each shard would take whatever entry is newest when it starts.
- Tests missing from the timings file (new or renamed) must still be assigned. pytest-split and the sequencer above give them the average duration. Keep the exactly-once check from Shard tests, because a sequencer bug skips tests silently.
- pytest-split's default `duration_based_chunks` algorithm breaks with pytest-randomly or pytest-random-order: shards can overlap or miss tests. Use `least_duration`.
- Save timings only from default-branch pushes. Pull request caches are scoped to their pull request anyway, and timings affect only balance, not which tests run.
- Cache entries unused for 7 days are evicted. Shards then fall back to count-based splits until the next default-branch run saves new timings.

## Verify

- Over three to five runs, the slowest shard should finish within about 15% of the fastest. Its p50 should be below the old slowest shard's p50 from the [baseline](https://berrybox.io/playbooks/baseline.md).
- The aggregate job's test count should match the count before the change.
- `gh cache list --key test-durations-` should show a new entry after each default-branch push.

## Sources

- EdgeDB (now Gel): [EdgeDB blog: split about 5,000 tests over 16 shards by recorded per-test runtimes](https://www.geldata.com/blog/how-we-sharded-our-test-suite-for-10x-faster-runs-on-github-actions). The suite took 2 hours and 22 minutes on a 2-core GitHub-hosted runner; split over 16 shards by recorded timings, it takes around 7 minutes, not counting the build step.
- Ramp: [Ramp Builders: replace pytest-xdist's test-to-worker assignment with a better packing algorithm](https://builders.ramp.com/post/faster-python-tests-part-two). The packing algorithm, tried as a proof of concept on a pytest fork, saved 2-3 minutes.
- Stripe: [stripe-ios: rebalance PaymentSheet UI tests across four jobs, with unassigned tests going to a catch-all shard](https://github.com/stripe/stripe-ios/pull/7333). With the tests rebalanced over four jobs, each running four simulator workers on larger machines, the slowest PaymentSheet UI job went from about 26 to about 12 minutes.
- Linear: [Linear Now: split oversized test files so file-based shards even out](https://linear.app/now/ci-bottleneck-reworked#balance-work-the-way-the-test-runner-sees-it). After splitting the largest test files and moving from four to eight shards, the slowest shard dropped from 5.25 to 4.33 minutes.
