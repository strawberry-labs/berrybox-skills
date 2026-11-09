# Quarantine flaky tests with an owner and an exit date

Collect tests that fail and pass again without a code change, move them out of the blocking job into a reviewed list with an owner, an issue and an expiry date, and keep running them where they can't block a merge.

- Playbook: [Make a red build mean something broke](https://berrybox.io/playbooks/flaky-tests.md)
- Saves: wait time and runner minutes
- Risk: medium
- Web page: https://berrybox.io/playbooks/flaky-tests/quarantine-flaky-tests

## Signals in your baseline

- The reruns files from narrow retries name the same tests week after week, on different branches.
- Runs on attempt 2 or later in the baseline JSON failed their first attempt in a test step.
- Tests are switched off with bare skip markers (skip, xit, t.Skip, @Disabled) that name no issue, owner or date.
- People rerun pull request checks because a test unrelated to their change failed.

## Why it works

Retries stop one flaky failure from failing a build, but the flaky test stays, and when it fails every attempt it blocks pull requests that never touched its code. Quarantine moves a known-flaky test out of the blocking job while it keeps running elsewhere, so a red build means something again and the test keeps producing evidence for whoever fixes it. Slack automated the loop for its mobile suites: detect the flaky test, disable it through a pull request, and file a ticket for the team that owns it.

Quarantine fails in two ways. It can hide real failures: Slack's first version filtered flaky results out of reports and treated tests without history as flaky, so a broken new test reached main. Or it becomes a graveyard of skipped tests nobody owns. An explicit list that names the owner, the issue and an exit date, reviewed like code, prevents both. Atlassian gives each owning team a ticket with a deadline and takes a test out of quarantine after it stays healthy for a set period.

## Apply it

### 1. Find the flaky tests

A flaky test fails and then passes on the same code. If you record retries as in [retry narrowly](https://berrybox.io/playbooks/flaky-tests/retry-narrowly.md), count how many branches each test needed a retry on:

```bash
gh run list --workflow ci.yml --limit 200 --json databaseId,headBranch \
  --jq '.[] | "\(.databaseId) \(.headBranch)"' |
while read -r id branch; do
  gh run download "$id" --pattern 'reruns-*' --dir "reruns/$id" >/dev/null 2>&1 || continue
  find "reruns/$id" -name reruns.txt -exec awk -v b="$branch" '{print $3, b}' {} +
done | sort -u | awk '{print $1}' | sort | uniq -c | sort -rn | head -20
```

A test that needed retries on two or more unrelated branches is a candidate. Without those files, find first-attempt failures with the query on the [flaky tests](https://berrybox.io/playbooks/flaky-tests.md) page, list a run's job IDs with `gh run view RUN_ID --attempt 1`, and read the failing tests with `gh run view --job JOB_ID --log-failed`. Before you quarantine, confirm the test is flaky rather than broken: Dropbox reruns a failing test on an earlier commit where it passed.

### 2. Keep the quarantine in one reviewed file

```json
[
  {
    "test": "tests/test_billing.py::test_webhook_retry",
    "owner": "@acme/payments",
    "issue": "https://github.com/acme/app/issues/1234",
    "expires": "2026-12-07"
  }
]
```

Save it as `quarantine.json`, and add `/quarantine.json @acme/ci-owners` to `CODEOWNERS` so every change to it needs a review.

### 3. Skip it in the blocking job, run it in another

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
      - name: Test without quarantined tests
        run: pytest $(jq -r '.[].test | "--deselect=" + .' quarantine.json)

  quarantined:
    runs-on: ubuntu-24.04
    timeout-minutes: 30
    steps:
      - uses: actions/checkout@v7
      - uses: actions/setup-python@v7
        with:
          python-version: "3.13"
      - run: pip install -r requirements-dev.txt
      - name: Warn about expired entries
        run: |
          jq -r --arg today "$(date -u +%F)" '.[] | select(.expires < $today)
            | "::warning title=Quarantine expired::\(.test) (owner \(.owner), \(.issue))"' quarantine.json
      - name: Run quarantined tests
        continue-on-error: true
        run: |
          tests=$(jq -r '.[].test' quarantine.json)
          if [ -n "$tests" ]; then pytest $tests --junitxml=quarantine.xml; fi
      - uses: actions/upload-artifact@v7
        if: always()
        with:
          name: quarantine-results
          path: quarantine.xml
          if-no-files-found: ignore
```

- The `test` job keeps its name, so branch protection still matches it. With an empty list, it runs everything.
- `continue-on-error` keeps the `quarantined` job green while its results go to the artifact. Never make it a required check.
- Also run the workflow on pushes to the default branch and on a nightly `schedule`, so quarantined tests keep running when pull requests are quiet.
- Take a test out in the pull request that fixes it, once it has passed every quarantine run for about two weeks.

The same list works with other runners:

- Go 1.20 or later: `go test ./... -skip '^(TestWebhookRetry|TestCacheEviction)$'` in the blocking job, and `-run` with the same pattern in the quarantine job.
- Playwright: tag the test with `{ tag: '@quarantine' }`, then run `--grep-invert @quarantine` in the blocking job and `--grep @quarantine` in the other.
- JUnit 5 with Gradle: add `@Tag("quarantine")`, and in `tasks.test { useJUnitPlatform { ... } }` call `includeTags("quarantine")` when the build gets `-Pquarantine` and `excludeTags("quarantine")` otherwise.

## Keep it safe

- **Required checks.** Keep the blocking job's name, and don't add the quarantine job to required checks: it is expected to fail.
- **Who can quarantine.** A pull request that adds its own failing test to the list would merge green, which is why the file needs a CODEOWNERS review (with "Require review from Code Owners" turned on). If a bot opens quarantine pull requests, run it on pushes to the default branch or on a schedule, never on `pull_request_target`, and give its token only the permissions it needs. Slack suppresses tests only from main-branch results.
- **Flaky, not broken.** A test that fails on every attempt on the default branch is broken: fix it or revert the change that broke it. Tests that fail at a date boundary, such as a new month, need a fix rather than a quarantine.
- **Lost coverage.** A quarantined test protects nothing, and its flakiness may be a real race in the code under test. Keep expiry dates two to four weeks out, cap the list (for example at 1% of tests), and have owners fix or delete rather than extend.
- **Silent skips.** `--deselect` matches node ID prefixes, so an entry such as `tests/test_billing.py` drops the whole file. Use full node IDs, and check that pytest's deselected count equals the number of entries.

## Verify

- After two weeks, rerun the [baseline](https://berrybox.io/playbooks/baseline.md). The Reruns column should fall, and so should failed runs on the default branch.
- The `test` and `quarantined` jobs together should run as many tests as the `test` job did before. Compare pytest's `passed` and `deselected` counts with the quarantine job's total.
- Every entry should have an owner, an open issue and a future date, and the list should shrink over time.
- Required checks still report under the same names.

## Sources

- Slack: [Slack Engineering: detect flaky mobile tests, disable them through an automatic pull request and file a ticket for the owning team](https://slack.engineering/handling-flaky-tests-at-scale-auto-detection-suppression/). Test job failures fell from 56.76% on July 27, 2020 to 3.85% on February 22, 2021.
- Atlassian: [Atlassian Engineering: quarantine flaky tests with owner tickets and deadlines, keep running them, and release them after a healthy period](https://www.atlassian.com/blog/atlassian-engineering/taming-test-flakiness-how-we-built-a-scalable-tool-to-detect-and-manage-flaky-tests). As of the last quarter, Flakinator had recovered more than 22,000 builds and identified 7,000 unique flaky tests.
- Dropbox: [Dropbox Tech: rerun a failing test on a commit where it passed before, and quarantine it automatically if it flaps across hosts](https://dropbox.tech/infrastructure/athena-our-automated-build-health-management-system). Athena doubled the number of test quarantines and removed the need for manual test quarantines from the team.
- Spotify: [Spotify Engineering: show each team a table of its tests with the slow and flaky ones marked](https://engineering.atspotify.com/2019/11/test-flakiness-methods-for-identifying-and-dealing-with-flaky-tests). Making the table available, and doing nothing else, reduced test flakiness at Spotify from 6% to 4% in two months.
