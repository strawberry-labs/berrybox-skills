# Make a red build mean something broke

Retry only what failed and record it, quarantine tests that keep flaking, stop new flaky tests in review, and remove the outside changes and network stalls that fail runs without a code change.

Web page: https://berrybox.io/playbooks/flaky-tests

## Signals in your baseline

- The Reruns column in the baseline is above a few percent for pull request workflows.
- Runs in the baseline JSON with an attempt of 2 or more succeeded without a new commit.
- The same test fails on unrelated pull requests in the same week.
- Jobs fail in checkout, install, image pull or service startup rather than in a test step.

A flaky failure costs more than the rerun. Each red build that turns out to be noise teaches people that red means "try again", and the next real failure gets the same treatment. These plays keep failures rare and meaningful: retry narrowly and write down what the retry hid, take known flaky tests out of the blocking path with someone responsible for them, keep new ones out, and remove causes that come from outside your code.

## Confirm it in your baseline

- The **Reruns** column counts runs on attempt 2 or later. Above a few percent on `pull_request` workflows, people are rerunning until the checks pass.
- In the `--json` output, take runs with `attempt` above 1 that ended in `success`, and list the jobs and steps that failed or were cut off the first time. Run it from the repository root:

```bash
jq -r '.runs[] | select(.attempt > 1 and .conclusion == "success") | .id' /tmp/ci-baseline.json |
while read -r run; do
  gh api --paginate "repos/{owner}/{repo}/actions/runs/$run/attempts/1/jobs?per_page=100" \
    --jq '.jobs[] | select(.conclusion == "failure" or .conclusion == "cancelled")
      | [.name, (.steps[]? | select(.conclusion == "failure" or .conclusion == "cancelled") | .name)] | @tsv'
done | sort | uniq -c | sort -rn
```

- Steps that run tests point at flaky tests. Failures in "Initialize containers", checkout, install or download steps point at infrastructure. A first attempt with no jobs was waiting for approval of a fork pull request, not flaking.
- In the workflow files, look for `image:` lines with `latest` or no tag, `curl` or `wget` calls without `--retry`, and retry wrappers around whole test commands.

## Order of work

Start with [retry narrowly](https://berrybox.io/playbooks/flaky-tests/retry-narrowly.md): it stops most reruns and produces the list of flaky tests the next play needs. [Quarantine](https://berrybox.io/playbooks/flaky-tests/quarantine-flaky-tests.md) the tests that keep showing up, each with an owner and a date, then [gate new tests](https://berrybox.io/playbooks/flaky-tests/gate-new-tests.md) so the list stops growing. [Pinned images](https://berrybox.io/playbooks/flaky-tests/pin-service-images.md) and [resilient network calls](https://berrybox.io/playbooks/flaky-tests/resilient-network.md) are low risk and can ship any time. Do them first if most failed attempts died before a test ran.

## Plays

- [Retry only the test or step that failed, and record the retry](https://berrybox.io/playbooks/flaky-tests/retry-narrowly.md): Rerun failed tests, or a failed download or service start, inside the same job two or three times at most, report every pass on retry as a flaky test, and never retry whole workflows, timeouts or steps with side effects. Saves wait time and runner minutes; medium risk.
- [Quarantine flaky tests with an owner and an exit date](https://berrybox.io/playbooks/flaky-tests/quarantine-flaky-tests.md): Collect tests that fail and pass again without a code change, move them out of the blocking job into a reviewed list with an owner, an issue and an expiry date, and keep running them where they can't block a merge. Saves wait time and runner minutes; medium risk.
- [Run new and changed tests many times before they can block merges](https://berrybox.io/playbooks/flaky-tests/gate-new-tests.md): When a pull request adds or edits tests, run just those tests 20 to 50 times with retries off, report the result as its own check, and fix any failure before the tests join the suite everyone waits on. Saves wait time and runner minutes; low risk.
- [Pin service images and tools to exact versions](https://berrybox.io/playbooks/flaky-tests/pin-service-images.md): Replace floating tags such as latest in services, containers, runner labels and tool installs with exact versions or digests, so a run changes only when a commit changes it, and take updates through reviewed pull requests. Saves wait time and runner minutes; low risk.
- [Put stall limits and bounded retries on every network fetch](https://berrybox.io/playbooks/flaky-tests/resilient-network.md): Make checkout, submodules, downloads and package installs give up on a stalled transfer within about a minute and retry it two or three times with backoff, so a bad connection costs seconds instead of a failed or hung job. Saves wait time and runner minutes; low risk.
