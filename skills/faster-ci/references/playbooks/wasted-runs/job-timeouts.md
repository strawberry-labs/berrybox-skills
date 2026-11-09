# Give every job a timeout that fits its normal runtime

A job without timeout-minutes can hang for six hours before GitHub stops it. Set each limit from the job's recorded p95 with about 2x headroom, so hangs fail in minutes and healthy runs never hit the limit.

- Playbook: [Stop paying for runs nobody needs](https://berrybox.io/playbooks/wasted-runs.md)
- Saves: runner minutes
- Risk: low
- Web page: https://berrybox.io/playbooks/wasted-runs/job-timeouts

## Signals in your baseline

- Jobs in the workflow files have no timeout-minutes, so they inherit the 360-minute default.
- The slowest-jobs table shows a p90 far above the p50, or cancelled jobs that ran for close to six hours.
- Annotations on cancelled jobs say the job exceeded the maximum execution time.
- Steps that wait on a simulator, an emulator, a service container or a download have no step-level timeout.

## Why it works

GitHub cancels a job after 360 minutes unless the job sets `timeout-minutes`. A test stuck in a loop, a deadlocked process, a simulator that never boots or a download with no timeout holds the runner for that whole time. The job fails anyway, just hours later, after billing every minute on a hosted runner and keeping one runner out of the pool. A limit close to the job's real runtime turns the six-hour hang into a failure a few minutes after the job should have finished, and the author learns about it the same hour.

## Apply it

Compute a starting limit for every job from the baseline JSON (`--json` output of the [baseline script](https://berrybox.io/playbooks/baseline.md)). The script takes the p95 of successful runs, doubles it and rounds up to the next 5 minutes:

```bash
python3 - /tmp/ci-baseline.json <<'EOF'
import json, math, sys
from collections import defaultdict

durations = defaultdict(list)
for run in json.load(open(sys.argv[1]))["runs"]:
    if run["conclusion"] == "success":
        for job in run["jobs"]:
            durations[(run["workflow"], job["name"])].append(job["duration"] / 60)

for (workflow, job), minutes in sorted(durations.items()):
    minutes.sort()
    p95 = minutes[math.ceil(0.95 * len(minutes)) - 1]
    limit = max(5, math.ceil(2 * p95 / 5) * 5)
    print(f"{workflow} | {job} | {len(minutes)} runs | p95 {p95:.1f} min | max {minutes[-1]:.1f} min | timeout-minutes: {limit}")
EOF
```

Then set the limits on each job, and on steps that wait for something outside the job:

```yaml
jobs:
  lint:
    runs-on: ubuntu-latest
    timeout-minutes: 10
    steps:
      - uses: actions/checkout@v7
      - run: make lint

  integration:
    runs-on: ubuntu-latest
    timeout-minutes: 25
    steps:
      - uses: actions/checkout@v7
      - name: Start services
        timeout-minutes: 5
        run: docker compose up --wait
      - run: make integration-test

  unit:
    strategy:
      matrix:
        os: [ubuntu-latest, macos-latest]
    runs-on: ${{ matrix.os }}
    timeout-minutes: ${{ matrix.os == 'macos-latest' && 30 || 15 }}
    steps:
      - uses: actions/checkout@v7
      - run: make unit-test
```

- `timeout-minutes` is valid on jobs and on steps. There is no workflow-level setting.
- Matrix jobs share one definition, and the baseline lists each leg separately. Use the slowest leg's number, or an expression on `matrix` as in the `unit` job when legs differ a lot.
- A step-level limit stops a wait that will never finish (services, emulators, network fetches) and names the step that hung, which is easier to debug than a whole-job timeout.
- A job that calls a reusable workflow with `uses:` can't set `timeout-minutes`. Set the limits on the jobs inside the called workflow.
- Jobs with fewer than about 20 successful runs in the sample get a noisy p95. Round those up generously.

## Keep it safe

- A limit that is too tight costs more than a missing one: every healthy run it cuts off needs a full rerun. Measure from runs that include cold caches, keep about 2x headroom, and raise the limit when a job grows for legitimate reasons instead of letting it trip.
- A job stopped by its timeout ends as `cancelled`, not `failure`. Required checks still block the merge, because cancelled doesn't count as passing. Retry bots, failure alerts and flaky-test tracking that only look for `failure` will miss timeouts unless you include `cancelled`.
- A timeout bounds a hang, it doesn't fix it. When a job starts hitting its limit, find the step that hangs instead of raising the number.
- Don't pair timeouts with `continue-on-error` on test steps. A step that timed out and was allowed to continue reports a passing job with tests that never finished.

## Verify

- Before merging, compare each new limit with the `max` column from the script. No successful run in the sample should exceed its limit.
- After a week, rerun the [baseline](https://berrybox.io/playbooks/baseline.md). The p90 of the affected jobs should come down if hangs were inflating it, and total runner minutes should drop by roughly the hours hung jobs used to burn.
- Find jobs that hit a limit: list cancelled runs with `gh run list --status cancelled`, then read a job's annotations with `gh api "repos/{owner}/{repo}/check-runs/JOB_ID/annotations" --jq '.[].message'`. A timeout says the job "has exceeded the maximum execution time". Each hit should be a real hang, not a slow healthy run.

## Sources

- Shopify: [job-iteration: add a 5-minute limit to a test matrix that finishes in under a minute](https://github.com/Shopify/job-iteration/pull/717)
- Spotify: [confidence-sdk-flutter: add job and test-step limits so a stuck iOS simulator can't run for hours](https://github.com/spotify/confidence-sdk-flutter/pull/72)
- Shopify: [tecnix: raise the test limit from 60 to 90 minutes after it cut off 10 of 96 runs](https://github.com/Shopify/tecnix/pull/74)
