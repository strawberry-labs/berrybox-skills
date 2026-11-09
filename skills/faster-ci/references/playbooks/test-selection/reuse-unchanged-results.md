# Reuse a passing result when a check's inputs haven't changed

Key each slow, deterministic check on a hash of everything it reads, record a pass when it succeeds, and skip the work when the same inputs already passed, while the check still reports under its usual name.

- Playbook: [Run only what a change can affect](https://berrybox.io/playbooks/test-selection.md)
- Saves: wait time and runner minutes
- Risk: medium
- Web page: https://berrybox.io/playbooks/test-selection/reuse-unchanged-results

## Signals in your baseline

- A slow check (an API diff, a generated-code check, an integration suite) runs on every push even when none of the files it reads changed.
- Bazel tests are tagged `external` or `no-cache` and never print `(cached) PASSED`, or Gradle test tasks never show `FROM-CACHE`.
- End-to-end jobs rebuild the frontend or an image on every run even when no file that feeds it changed.

## Why it works

A deterministic check is a function of its inputs. If the same inputs already passed, running the check again proves nothing new. Dropbox applies this to tests: when a commit doesn't affect a test, the test keeps the status it had on the commit before. Build tools with content-addressed caches (Bazel, Gradle, Turborepo, Nx, Go) already skip tests whose inputs match an earlier passing run, as long as the tests are hermetic. For checks that live outside those tools, you can do the same in the workflow: hash the inputs, look for a record that they passed, and skip the work when you find one.

## Apply it

### A pass marker in the Actions cache

```yaml
name: api-check
on:
  pull_request:
  merge_group:
  push:
    branches: [main]
  schedule:
    - cron: "23 4 * * *"

permissions:
  contents: read

jobs:
  api-check:
    runs-on: ubuntu-latest
    timeout-minutes: 30
    steps:
      - uses: actions/checkout@v7
      - id: marker
        if: github.event_name != 'schedule'
        uses: actions/cache/restore@v6
        with:
          path: .ci-pass/api-check
          key: api-check-v1-${{ runner.os }}-${{ hashFiles('src/**', 'package-lock.json', 'scripts/api-check.sh', '.github/workflows/api-check.yml') }}
          lookup-only: true
      - if: steps.marker.outputs.cache-hit != 'true'
        run: ./scripts/api-check.sh
      - if: steps.marker.outputs.cache-hit != 'true'
        run: mkdir -p .ci-pass && date -u > .ci-pass/api-check
      - if: steps.marker.outputs.cache-hit != 'true' && github.event_name != 'schedule'
        uses: actions/cache/save@v6
        with:
          path: .ci-pass/api-check
          key: ${{ steps.marker.outputs.cache-primary-key }}
      - if: steps.marker.outputs.cache-hit == 'true'
        run: echo "api-check skipped, these inputs already passed" >> "$GITHUB_STEP_SUMMARY"
```

- The key hashes every file the check reads, plus the script and this workflow file. `v1` is a manual switch: bump it to invalidate every marker.
- `lookup-only: true` checks whether the key exists without downloading anything.
- The marker is saved only after the check passes, because a failing step stops the job. Failures are never recorded.
- Pull requests can read markers saved on the default branch, so a pull request that doesn't touch the inputs skips in seconds. Markers a pull request saves are visible only to that pull request.
- The nightly run skips the lookup and runs the check for real.

### Build tools that already cache results

- **Bazel** reruns a test only when its inputs change, unless it is tagged `external` or `no-cache`, or failed last time. Make tests hermetic so you can drop those tags, as Uber did for its Docker suites. With a remote cache, let only default-branch runs write and set `--remote_upload_local_results=false` on pull requests.
- **Gradle** treats `Test` tasks as cacheable. With the build cache from [compiler caches](https://berrybox.io/playbooks/slow-builds/compiler-cache.md), unchanged modules show `FROM-CACHE` for `test`.
- **Turborepo and Nx** replay a cached `test` task's logs when its inputs match. Declare the inputs carefully.
- **Go** caches passing package results in `GOCACHE`. Restoring it makes unchanged packages print `(cached)`.

The same idea covers build artifacts. Slack's end-to-end jobs skip the frontend build when no frontend file changed and reuse a recent production build instead.

## Keep it safe

- **Complete keys.** Every input belongs in the key: source, fixtures, lockfile, tool versions, the script and the workflow. `hashFiles` returns an empty string when a pattern matches nothing, which makes the key constant, so check that each pattern matches.
- **Deterministic checks only.** Don't reuse results for tests that call the network, depend on the date or are flaky.
- **Who writes.** Pull request runs can only write markers their own pull request sees. Never run this from `pull_request_target`, where a pull request could write to the default branch's cache. Give pull requests read-only access to a Bazel remote cache.
- **Required checks still report.** A hit still runs the job, which passes in seconds under the same name. Don't swap it for a trigger-level `paths` filter.
- **Keep the net.** The nightly run ignores markers. If it fails, find the input your key missed before you trust the markers again.

## Verify

- Push a commit that doesn't touch the inputs, such as a README edit. The job should finish in seconds and write the skip line to the step summary. A change to `src/` should run the check.
- Compare the job's p50 and runner minutes with the [baseline](https://berrybox.io/playbooks/baseline.md), and count the share of runs that hit.
- For Bazel, count `(cached) PASSED` lines. For Gradle, count `test` tasks marked `FROM-CACHE`.
- The nightly run passes, and every pull request still reports the same checks.

## Sources

- Stripe: [stripe-ios: cache the generated API baseline by revision, toolchain and build settings, and skip changes that can't affect the API](https://github.com/stripe/stripe-ios/pull/7336). With a cached baseline, API check times fell from about 14 minutes to about 4.
- Uber: [submitqueue: make the Docker test suites hermetic and drop the external tag so Bazel caches their results](https://github.com/uber/submitqueue/pull/439)
- Dropbox: [Dropbox blog: carry a test's last result forward to commits that can't affect it](https://dropbox.tech/infrastructure/continuous-integration-and-deployment-with-bazel)
- Slack: [Slack engineering: reuse a recent prebuilt frontend for end-to-end runs when no frontend code changed](https://slack.engineering/speedup-e2e-testing/). Reusing prebuilt frontend assets cut frontend build frequency by 60%.
