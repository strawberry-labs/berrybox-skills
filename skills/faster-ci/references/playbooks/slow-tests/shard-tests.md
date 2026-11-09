# Split a long test suite across parallel jobs

Run the suite as a matrix of shards with the test runner's own shard flag, gate merges on one aggregate job, merge the shard reports and confirm that every test ran exactly once.

- Playbook: [Make the test suite finish sooner](https://berrybox.io/playbooks/slow-tests.md)
- Saves: wait time
- Risk: medium
- Web page: https://berrybox.io/playbooks/slow-tests/shard-tests

## Signals in your baseline

- The long pole in the baseline is a test job, and its test step accounts for most of that job's time.
- The test step takes at least three times as long as checkout, install and build combined.
- The whole suite runs in one job, with no matrix and no --shard, --splits or --group flag in the test command.

## Why it works

A test runner already spreads work over one machine's cores. Sharding spreads it over machines: the same job runs N times, and each copy runs a fixed 1/N of the tests. Jest, Vitest and Playwright take `--shard=i/n`; the pytest-split plugin gives pytest `--splits n --group i`. Each shard computes its own share from the same test list, so no coordinator is needed as long as every shard sees the same files and n.

Setup doesn't split. Every shard repeats checkout, install, build and service startup, so a shard takes about setup + tests ÷ N, and each run pays for setup N times. With 2 minutes of setup and 24 minutes of tests:

| Shards | Slowest shard | Billed runner minutes |
|---:|---:|---:|
| 1 | 26 min | 26 |
| 4 | 8 min | 32 |
| 8 | 5 min | 40 |
| 16 | 3.5 min | 64 |

No shard count gets below setup plus the largest test file, since Jest and Vitest move whole files. Once tests ÷ N nears setup, another doubling saves little wall time, adds N more setups and rounds N more jobs up to whole minutes. Shrink setup first ([Slow setup](https://berrybox.io/playbooks/slow-setup.md), [Build once](https://berrybox.io/playbooks/critical-path/build-once.md)) to make more shards pay.

## Apply it

Start with N = test step ÷ (2 × setup), rounded down and kept below the number of test files: Vitest rejects a larger count, and a Jest shard with nothing to run fails with "No tests found". Turn the test job into a matrix, and give the old job ID and name to a small aggregate job so the required check keeps its name.

### Vitest or Jest

```yaml
permissions:
  contents: read

jobs:
  test-shard:
    name: test (${{ matrix.shard }}/${{ strategy.job-total }})
    runs-on: ubuntu-latest
    timeout-minutes: 20
    strategy:
      fail-fast: false
      matrix:
        shard: [1, 2, 3, 4]
    steps:
      - uses: actions/checkout@v7
      - uses: actions/setup-node@v7
        with:
          node-version: 24
          cache: npm
      - run: npm ci
      - name: Run shard
        run: >-
          npx vitest run
          --shard=${{ matrix.shard }}/${{ strategy.job-total }}
          --reporter=default --reporter=junit
          --outputFile.junit=reports/junit-${{ matrix.shard }}.xml
      - if: ${{ !cancelled() }}
        uses: actions/upload-artifact@v7
        with:
          name: junit-shard-${{ matrix.shard }}
          path: reports/
          retention-days: 7
          overwrite: true

  test:
    if: ${{ always() }}
    needs: test-shard
    runs-on: ubuntu-latest
    timeout-minutes: 5
    steps:
      - uses: actions/download-artifact@v8
        with:
          pattern: junit-shard-*
          path: reports
          merge-multiple: true
      - name: Merge shard reports and check that each test ran once
        run: |
          python3 - <<'EOF'
          import collections, glob, xml.etree.ElementTree as ET
          merged, runs = ET.Element("testsuites"), collections.Counter()
          for path in sorted(glob.glob("reports/*.xml")):
              for suite in ET.parse(path).getroot().iter("testsuite"):
                  merged.append(suite)
                  runs.update((case.get("classname"), case.get("name")) for case in suite.iter("testcase"))
          ET.ElementTree(merged).write("junit.xml", encoding="utf-8", xml_declaration=True)
          repeated = sorted(test for test, count in runs.items() if count > 1)
          print(f"{sum(runs.values())} tests ran across shards; {len(repeated)} ran in more than one shard")
          for classname, name in repeated[:20]:
              print(f"  ran twice: {classname} {name}")
          raise SystemExit(1 if repeated else 0)
          EOF
      - uses: actions/upload-artifact@v7
        with:
          name: test-report
          path: junit.xml
          overwrite: true
      - name: Require every shard to pass
        if: ${{ needs.test-shard.result != 'success' }}
        run: exit 1
```

- `strategy.job-total` counts the jobs in the matrix, so the `--shard` denominator always matches. Use it only when `shard` is the only matrix key.
- `fail-fast: false` lets every shard finish, so one run reports every failure.
- Shards upload JUnit XML even when tests fail, and `overwrite: true` lets a re-run shard replace its report.
- The aggregate job runs with `if: always()` and fails unless `needs.test-shard.result` is `success`, so a failed, cancelled or skipped shard blocks the merge. Without `always()` it would be skipped, and a skipped job satisfies a required check.
- The Python step merges the reports into one `junit.xml`, prints the test count and fails if any test ran in two shards. It needs no checkout or install.

For Jest, run `npx jest --ci --shard=${{ matrix.shard }}/${{ strategy.job-total }} --reporters=default --reporters=jest-junit` with `JEST_JUNIT_OUTPUT_FILE` set to the same path and `JEST_JUNIT_CLASSNAME: "{filepath}"`, so every test ID includes its file.

### Playwright

```yaml
      - run: npx playwright install --with-deps
      - name: Run shard
        run: npx playwright test --shard=${{ matrix.shard }}/${{ strategy.job-total }} --reporter=blob,junit
        env:
          PLAYWRIGHT_JUNIT_OUTPUT_FILE: reports/junit-${{ matrix.shard }}.xml
          PLAYWRIGHT_JUNIT_INCLUDE_PROJECT_IN_TEST_NAME: "true"
```

The project name keeps a test that runs in two browser projects from counting as a duplicate. `fullyParallel: true` splits by test instead of by file, which balances better once tests are independent ([Isolate test state](https://berrybox.io/playbooks/slow-tests/isolate-test-state.md)). For one HTML report, upload each shard's `blob-report` as `blob-report-<shard>`; a job that no check requires downloads them into `all-blob-reports` (`pattern: blob-report-*`, `merge-multiple: true`) and runs `npx playwright merge-reports --reporter html ./all-blob-reports`.

### pytest

```yaml
      - uses: actions/setup-python@v7
        with:
          python-version: "3.13"
          cache: pip
      - run: pip install -r requirements-dev.txt pytest-split
      - name: Run shard
        run: >-
          pytest --splits ${{ strategy.job-total }} --group ${{ matrix.shard }}
          --junitxml=reports/junit-${{ matrix.shard }}.xml
```

Without a durations file, pytest-split divides the tests by count. [Balance shards](https://berrybox.io/playbooks/slow-tests/balance-shards.md) adds recorded timings.

## Keep it safe

- Require the aggregate check, not the shard checks. Shard names such as `test (2/4)` change with N; the aggregate's doesn't, so changing N never touches branch protection. Copy the old job's `name:` exactly, if it had one.
- Per-shard coverage thresholds fail, because each shard runs part of the suite. Check them once on merged coverage (`coverage combine`, or Vitest's `--merge-reports` with coverage on).
- Shards that share a remote resource (a test account, a staging database, a rate-limited API) now hit it at once. Put `${{ github.run_id }}-${{ matrix.shard }}` in the names of anything they create.
- Reports and Playwright traces contain test output, and anyone who can read the repository can download artifacts. Keep `retention-days` short and secrets out of test logs.

## Verify

- Compare the slowest shard with the old test job's p50 in the [baseline](https://berrybox.io/playbooks/baseline.md). Expect about setup + test step ÷ N, and a matching drop in wall time.
- Runner minutes should rise by about (N − 1) × setup per run. Report both.
- The test count in the aggregate log should equal the passed plus skipped count of an unsharded run of the same commit.
- Once, list each shard's tests and diff them against the full list. Every test should appear exactly once:

```bash
# pytest with pytest-split
pytest --collect-only -q | grep '::' | sort > all.txt
for i in 1 2 3 4; do pytest --collect-only -q --splits 4 --group "$i"; done | grep '::' | sort > shards.txt
diff all.txt shards.txt && echo "each test is in exactly one shard"

# Playwright
npx playwright test --list | grep ' › ' | sort > all.txt
for i in 1 2 3 4; do npx playwright test --list --shard="$i/4"; done | grep ' › ' | sort > shards.txt
diff all.txt shards.txt && echo "each test is in exactly one shard"
```

## Sources

- Shopify: [Shopify CLI: run the Playwright E2E suite on two shards, each uploading artifacts under its own name](https://github.com/Shopify/cli/pull/7350)
- Spotify: [confidence-cli: shard Vitest E2E tests over four runners behind one stable check name](https://github.com/spotify/confidence-cli/pull/73)
- OpenAI: [codex: run Windows Bazel tests as four shard jobs behind the existing required check](https://github.com/openai/codex/pull/22408). The four Windows shards finished in about 7m29s, against a recent median of about 22m26s for the single job.
- Linear: [Linear Now: shrink per-shard setup before doubling from four to eight shards](https://linear.app/now/ci-bottleneck-reworked#sharding-is-limited-by-setup-overhead). Before the setup work, four shards spent 8.3 minutes on setup; afterward, eight shards spent 7.5 minutes.
