# Retry only the test or step that failed, and record the retry

Rerun failed tests, or a failed download or service start, inside the same job two or three times at most, report every pass on retry as a flaky test, and never retry whole workflows, timeouts or steps with side effects.

- Playbook: [Make a red build mean something broke](https://berrybox.io/playbooks/flaky-tests.md)
- Saves: wait time and runner minutes
- Risk: medium
- Web page: https://berrybox.io/playbooks/flaky-tests/retry-narrowly

## Signals in your baseline

- The baseline Reruns column is above a few percent, and the reruns pass without a new commit.
- Test commands run without a retry option, so one flaky test fails the job and someone reruns all of it.
- Workflows retry broadly: a retry action around the whole test command, a bot that reruns failed runs, or automatic retries of timed-out jobs.
- Jobs fail on a download, an image pull or a service start, and the fix is always a manual rerun.

## Why it works

A flaky failure and a real one look the same the first time. Running the failed test again, in the same job against the same build, tells them apart in seconds: a real bug fails again, and a flake usually passes. Rerunning the whole workflow answers the same question at the cost of a full run. Broad retries also waste work on failures that can't recover: Bun found that most automatic retries of timed-out test shards timed out again.

Keep the attempts few and fixed, and treat every pass on retry as a finding. Shopify retries a failed test up to three times and tells developers which tests passed only after a retry. GitHub retries a failed test three ways (same process, clock moved forward, another host) to tell chance, time and test order apart, and assigns high-impact flakes to the people who last changed them. Without that record, retries hide a flaky test until it fails every attempt.

## Apply it

### Retry failed tests in the test runner

Use the runner's own retry, so only the failed tests run again:

| Runner | Retry only failed tests | Retried tests show up in |
|---|---|---|
| pytest | `pytest-rerunfailures`: `--reruns 2` | `RERUN` lines with `-rR` |
| Playwright | `retries: process.env.CI ? 2 : 0` in the config | the `flaky` status |
| Jest | `jest.retryTimes(2, { logErrorsBeforeRetry: true })` in the test file | errors logged before each retry |
| Go | `gotestsum --rerun-fails=2 --rerun-fails-report=reruns.txt --packages=./...` | the report file |
| Gradle | `org.gradle.test-retry`: `retry { maxRetries = 2; maxFailures = 20 }` | one report entry per execution |
| Maven | `-Dsurefire.rerunFailingTestsCount=2` | `flakyFailure` in the XML |

A complete pytest job that also records which tests needed a retry:

```yaml
jobs:
  test:
    runs-on: ubuntu-24.04
    timeout-minutes: 30
    steps:
      - uses: actions/checkout@v7
      - uses: actions/setup-python@v7
        with:
          python-version: "3.13"
      - run: pip install -r requirements-dev.txt
      - name: Test, retrying failed tests up to twice
        shell: bash
        run: pytest --reruns 2 --reruns-delay 1 --max-suite-reruns 20 -rR | tee pytest.log
      - name: Record tests that needed a retry
        if: always()
        shell: bash
        run: |
          grep '^RERUN ' pytest.log | sort | uniq -c > reruns.txt || true
          if [ -s reruns.txt ]; then
            echo "::warning title=Flaky tests::$(wc -l < reruns.txt) test(s) were retried"
            { echo '### Tests that needed a retry'; echo; sed 's/^/    /' reruns.txt; } >> "$GITHUB_STEP_SUMMARY"
          fi
      - uses: actions/upload-artifact@v7
        if: always()
        with:
          name: reruns-${{ github.job }}-${{ strategy.job-index }}
          path: reruns.txt
          if-no-files-found: ignore
```

- Pin `pytest-rerunfailures` in `requirements-dev.txt` like any other test dependency.
- `shell: bash` adds `-o pipefail`. Without it, `pytest | tee` reports success even when tests fail.
- `--max-suite-reruns 20` stops retrying when many tests fail at once, which signals a real break. gotestsum (`--rerun-fails-max-failures`, 10 by default) and Gradle (`maxFailures`) have the same guard.
- `strategy.job-index` keeps artifact names unique across matrix jobs. These files feed [quarantine](https://berrybox.io/playbooks/flaky-tests/quarantine-flaky-tests.md).

### Retry a failed infrastructure step

Shopify retries failed setup (loading a container, installing dependencies, `git fetch`) inside the job instead of starting over. This `run` script for a service-start step tries three times and warns when it needed a retry:

```bash
for attempt in 1 2 3; do
  if docker compose up --wait --wait-timeout 120; then
    [ "$attempt" -gt 1 ] && echo "::warning title=Retried setup::services started on attempt $attempt"
    exit 0
  fi
  docker compose down --volumes
  sleep $((attempt * 15))
done
exit 1
```

For downloads and checkout, use the stall limits in [resilient network calls](https://berrybox.io/playbooks/flaky-tests/resilient-network.md).

### Never retry these

- **Whole workflows or jobs.** Automatic reruns double runner minutes and hide flakes. Rerun a job automatically only when its runner was lost and it produced no result, and only once, as Bun's rules do. Otherwise a person runs `gh run rerun RUN_ID --failed`.
- **Timeouts.** A test or job that hit its limit is hung or too slow, and a retry usually ends the same way. See [job timeouts](https://berrybox.io/playbooks/wasted-runs/job-timeouts.md).
- **Deterministic checks** such as compiling, type checks, lint and formatting.
- **Steps with side effects**: deploys, migrations, publishing and notifications. A retry after a partial success can apply the change twice.

## Keep it safe

- **Required checks.** Check names don't change, and a test that fails every attempt still fails the job. Don't fake a retry with `continue-on-error`, which lets the job pass when the step fails.
- **Flakes still need fixing.** A retry can hide a real race in the code under test. Google found that failing a flaky-marked test only after three failures in a row encouraged people to ignore flakiness. Keep attempts at two or three, read the reruns list weekly, and quarantine repeat offenders.
- **Shared state.** pytest-rerunfailures keeps module- and session-scoped fixtures between attempts. A test that passes only on its second attempt may depend on test order; see [isolate test state](https://berrybox.io/playbooks/slow-tests/isolate-test-state.md).
- **Security.** A retry reruns the same code with the same token and secrets. Don't add a `workflow_run` rerun bot with `actions: write` that acts on fork pull requests, don't `set -x` in loops that handle tokens, and never skip TLS or checksum checks to get a download through.
- **Time budget.** Size `timeout-minutes` for the first run plus a few retried tests, not a second full run.

## Verify

- After one or two weeks, rerun the [baseline](https://berrybox.io/playbooks/baseline.md). The Reruns column for the changed workflows should fall, and Success should rise.
- If the baseline showed reruns, the reruns files shouldn't stay empty.
- The test job's p50 wall time should barely move; its p90 can rise slightly on runs that retried.
- The first attempt should run as many tests as before (pytest's summary line, gotestsum's `DONE` line), and every required check should report under its old name. Gradle and Surefire list each execution, so count unique test names.

## Sources

- Shopify: [Shopify Engineering: retry a failed test up to three times, retry setup failures inside the job, and flag tests that pass on retry](https://shopify.engineering/unreasonable-effectiveness-test-retries-android-monorepo-case-study). The Android pipeline pass rate rose from 31% to almost 90% after retries were applied to the sources of flakiness, along with some Gradle caching.
- GitHub: [GitHub blog: retry a failed test three ways to classify the flake, keep the build green and assign an issue to the likely author](https://github.blog/engineering/infrastructure/reducing-flaky-builds-by-18x/). Commits with a red build caused by a flaky test fell from 1 in 11 (about 9 percent) to less than half a percent (1 in 200).
- Google: [Google Testing Blog: re-run only the failing tests, and report a test marked flaky as failed only after three failures in a row](https://testing.googleblog.com/2016/05/flaky-tests-at-google-and-how-we.html)
- Bun: [bun: limit automatic Buildkite retries to lost or restarted agents and failed bootstraps, so a timed-out test shard runs once](https://github.com/oven-sh/bun/pull/34684). Over about 200 builds, the old rules retried about 670 timed-out test shards; 465 of those retries timed out again and 182 were canceled before finishing, which the PR calls 97% wasted.
