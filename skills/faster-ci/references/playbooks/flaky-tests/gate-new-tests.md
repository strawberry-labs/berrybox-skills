# Run new and changed tests many times before they can block merges

When a pull request adds or edits tests, run just those tests 20 to 50 times with retries off, report the result as its own check, and fix any failure before the tests join the suite everyone waits on.

- Playbook: [Make a red build mean something broke](https://berrybox.io/playbooks/flaky-tests.md)
- Saves: wait time and runner minutes
- Risk: low
- Web page: https://berrybox.io/playbooks/flaky-tests/gate-new-tests

## Signals in your baseline

- Most tests that your history or quarantine list marks as flaky were added or edited in the last few weeks.
- Pull requests add test files that run once before merge and go straight into a required job.
- New end-to-end or integration tests start failing on other people's pull requests soon after they land.

## Why it works

A flaky test is cheapest to fix before it merges, while its author still has the context and before it has blocked anyone else. One green run in review proves little, because a test that fails one run in 50 will usually pass it. Running only the tests a pull request adds or edits, many times in a row, costs minutes rather than a full suite, and it catches the timing, ordering and shared-state bugs that new tests often carry.

Teams that do this put the check where the author will see it. Mozilla runs each new or modified test 10 times, then 5 more times in a new browser instance each time, then repeats the sequence in chaos mode, within about an hour per task. Spotify's Flakybot lets an engineer run a pull request's tests and get a flakiness report before merging. Shopify's mobile team admits a new end-to-end test to blocking CI only after a dedicated pipeline has run it multiple times under a failure threshold. Uber ran a repaired integration test 50 times with Bazel's `--runs_per_test` before merging the fix. Repetition finds the frequent flakes. Rare ones still slip through, so keep [narrow retries](https://berrybox.io/playbooks/flaky-tests/retry-narrowly.md) and [quarantine](https://berrybox.io/playbooks/flaky-tests/quarantine-flaky-tests.md) as the backstop.

## Apply it

Add a workflow that lists the test files a pull request adds or edits and runs them repeatedly with retries off:

```yaml
name: Changed test stability

on:
  pull_request:

permissions:
  contents: read

jobs:
  repeat-changed-tests:
    runs-on: ubuntu-24.04
    timeout-minutes: 20
    steps:
      - uses: actions/checkout@v7
        with:
          fetch-depth: 2
      - name: List added or edited test files
        id: changed
        run: |
          files=$(git diff --name-only --diff-filter=AM HEAD^1 HEAD -- tests/ \
            | grep -E '(^|/)test_[^/]*\.py$' | head -n 20 | tr '\n' ' ')
          echo "files=$files" >> "$GITHUB_OUTPUT"
      - uses: actions/setup-python@v7
        if: steps.changed.outputs.files != ''
        with:
          python-version: "3.13"
      - name: Install dependencies
        if: steps.changed.outputs.files != ''
        run: pip install -r requirements-dev.txt
      - name: Run each changed test 30 times, retries off
        if: steps.changed.outputs.files != ''
        env:
          FILES: ${{ steps.changed.outputs.files }}
        run: pytest -p no:rerunfailures --count=30 -x $FILES
```

- In a `pull_request` run, `HEAD` is GitHub's merge commit and `HEAD^1` is the base branch, so `fetch-depth: 2` is enough for the diff. `--diff-filter=AM` keeps added and modified files and skips deleted ones.
- `head -n 20` caps the work when a pull request rewrites many tests at once.
- `--count=30` comes from `pytest-repeat`, which belongs in `requirements-dev.txt`. `-x` stops at the first failure, and `-p no:rerunfailures` turns off retries that would hide the flake you are looking for.
- File names come from the pull request, so they reach the shell through `env`, not through `${{ }}` inside the script.
- The step-level `if` conditions keep the job green when no tests changed.

### Go

Run every test in the packages whose `_test.go` files changed, in random order and with the race detector:

```bash
pkgs=$(git diff --name-only --diff-filter=AM HEAD^1 HEAD -- '*_test.go' | xargs -r -n1 dirname | sort -u | sed 's|^|./|')
if [ -n "$pkgs" ]; then go test -count=20 -shuffle=on -race $pkgs; fi
```

### Playwright

With the same `fetch-depth: 2` checkout, `npx playwright test --only-changed=HEAD^1 --repeat-each=20 --retries=0` runs the test files changed against the base branch 20 times each. `--retries=0` overrides the retries in your config.

Start the job as an optional check. After two weeks without false alarms, add it to the required checks, so the pull request that adds a flaky test is the one it blocks.

## Keep it safe

- **Required checks.** Once required, the job must report on every pull request. Keep the step-level `if` conditions rather than a trigger-level `paths` filter, which would leave the check pending forever on pull requests without test changes. Renaming the job later breaks branch protection.
- **Security.** Use `pull_request`, never `pull_request_target`: this job runs the pull request's own code, so it gets a read-only token and no secrets. Never interpolate file names into `run` with `${{ }}`, where a crafted name could inject shell commands.
- **Cost.** Repeats multiply runtime. Keep the file cap and `timeout-minutes`. Tests that call real services 30 times can hit rate limits; fake those services first ([fake slow services](https://berrybox.io/playbooks/slow-tests/fake-slow-services.md)).
- **Blind spots.** Repeating a test in one process can miss failures that depend on other test files or on order. Shuffle where the runner supports it, and see [isolate test state](https://berrybox.io/playbooks/slow-tests/isolate-test-state.md). `pytest-repeat` runs `unittest.TestCase` classes only once, with a warning.
- **Coverage.** This job adds a check. The normal test job still runs every test.

## Verify

- Open a throwaway pull request that adds a test failing about one run in five, such as `assert random.random() > 0.2`. The new check should fail. Close the pull request.
- Over the next month, look at where new quarantine entries come from. Fewer of them should be tests added in the last few weeks.
- In the [baseline](https://berrybox.io/playbooks/baseline.md), the new job should only take minutes, and only on pull requests that touch tests.
- The main test job should run the same number of tests as before, and every required check should report under its old name.

## Sources

- Mozilla: [Firefox source docs: run each new or modified test repeatedly, in fresh browser instances and then in chaos mode](https://firefox-source-docs.mozilla.org/testing/test-verification/index.html)
- Spotify: [Spotify Engineering: Flakybot runs a pull request's tests and reports whether they are flaky before merge](https://engineering.atspotify.com/2019/11/test-flakiness-methods-for-identifying-and-dealing-with-flaky-tests)
- Shopify: [Shopify Engineering: admit a new mobile end-to-end test to blocking CI only after a dedicated pipeline runs it repeatedly under a failure threshold](https://shopify.engineering/mobile-e2e-testing)
- Uber: [submitqueue: run a repaired integration test 50 times with --runs_per_test before merging the fix](https://github.com/uber/submitqueue/pull/274)
