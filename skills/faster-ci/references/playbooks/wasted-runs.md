# Stop paying for runs nobody needs

Cancel runs a newer push replaced, run each commit once, skip jobs whose inputs didn't change and put a ceiling on runaway jobs, without losing a required check.

Web page: https://berrybox.io/playbooks/wasted-runs

## Signals in your baseline

- Several runs of the same workflow overlap on one pull request, and the older ones finish anyway.
- The same commit starts both a push run and a pull_request run.
- Pull requests that only touch docs or config still run every build and test job.
- Some jobs have no timeout-minutes and occasionally run for hours before failing.

Waste is the cheapest place to start. These plays don't make any single job faster: they stop runs whose results nobody will read. That frees runners for the work that matters, so queues shrink when people or agents push in bursts, and the bill drops without touching a test.

## Confirm it in your baseline

- Look at the **Cancelled** and **Runs** columns for workflows triggered by `pull_request`. Zero cancellations on a busy repository usually means superseded runs are finishing anyway.
- Compare the `push` and `pull_request` rows. If a workflow runs on both for the same branches, every pull request commit is paying twice.
- Check the shortest pull requests in `gh pr list --state merged`. If a one-line README change ran the full suite, path filtering will pay off.
- Sort the slowest jobs by p90 rather than p50. A p90 far above the median often hides hung jobs that sat until GitHub's six-hour limit.

## Order of work

Start with the low-risk plays: cancel stale runs, deduplicate triggers and add timeouts. They change no test and rarely need a second look. Path filtering and draft gating save more on busy repositories but interact with required checks, so read their safety notes before applying them.

## Plays

- [Cancel runs a newer push replaced](https://berrybox.io/playbooks/wasted-runs/cancel-stale-runs.md): Group each workflow's runs by pull request so a new push cancels the run it made obsolete, and leave default-branch, release and deploy runs alone. Saves runner minutes; low risk.
- [Run CI once per commit instead of on both push and pull_request](https://berrybox.io/playbooks/wasted-runs/one-run-per-commit.md): A workflow that triggers on every push and on pull_request runs each pull request commit twice. Limit push to the default branch so each commit gets one run. Saves runner minutes; low risk.
- [Give every job a timeout that fits its normal runtime](https://berrybox.io/playbooks/wasted-runs/job-timeouts.md): A job without timeout-minutes can hang for six hours before GitHub stops it. Set each limit from the job's recorded p95 with about 2x headroom, so hangs fail in minutes and healthy runs never hit the limit. Saves runner minutes; low risk.
- [Skip jobs whose inputs didn't change, without stranding required checks](https://berrybox.io/playbooks/wasted-runs/skip-unchanged-paths.md): Detect changed paths in a first job, skip unaffected jobs with job-level if conditions and require one aggregate job, so small pull requests stop running everything while required checks keep reporting. Saves wait time and runner minutes; medium risk.
- [Hold expensive checks until a draft pull request is ready for review](https://berrybox.io/playbooks/wasted-runs/hold-draft-prs.md): Skip the slow jobs while a pull request is still a draft and start them when it is marked ready, so pushes of unfinished work get quick checks instead of the full suite. Saves runner minutes; medium risk.
- [Don't start a runner for comments, labels and edits your jobs ignore](https://berrybox.io/playbooks/wasted-runs/ignore-noise-events.md): Comment, label, review and description-edit events can start full workflow runs and cancel real ones. Keep them out of the workflow that reports required checks, and gate the workflows that need them with job-level conditions. Saves runner minutes; medium risk.
