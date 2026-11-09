# Cut the time jobs wait for a runner

Measure queue time per runner label, find out whether a concurrency cap, a cold pool or a burst of jobs causes it, and fix that cause with higher limits, split runner groups, warm capacity or fewer jobs.

- Playbook: [Give the long pole the right machine](https://berrybox.io/playbooks/runners.md)
- Saves: wait time
- Risk: medium
- Web page: https://berrybox.io/playbooks/runners/cut-queue-time

## Signals in your baseline

- The baseline shows a p50 queue above about 30 seconds, or waits of several minutes, for jobs on one runner label.
- Queue time peaks at the same hours each day, when people and agents push the most.
- Jobs on macOS, larger or self-hosted runners wait far longer than jobs on ubuntu-latest.
- One push starts more jobs at once, across matrix entries and shards, than the plan or pool can run concurrently.

## Why it works

Queue time is the gap between GitHub creating a job and a runner starting it. It adds straight to wall time, it isn't billed, and no faster machine wins it back. It has three common causes, and each has a different fix:

- **A concurrency cap.** GitHub-hosted standard runners allow 20 concurrent jobs on Free, 40 on Pro, 60 on Team and 500 on Enterprise, with macOS capped at 5 on every plan except Enterprise (50). Each larger runner and self-hosted pool also has its own maximum.
- **A cold pool.** Larger runners and autoscaled self-hosted pools create machines on demand. GitHub keeps larger-runner VMs warm for a while after use, but the first jobs after a quiet spell wait for new ones, and a self-hosted VM may need minutes to boot and warm its caches.
- **Bursts.** One push can start forty matrix jobs, and agents can push to many branches at once.

## Apply it

### Measure the wait per label

```sh
gh api "repos/{owner}/{repo}/actions/runs?per_page=100&status=completed" --jq '.workflow_runs[].id' |
  while read -r id; do
    gh api "repos/{owner}/{repo}/actions/runs/$id/jobs?per_page=100" \
      --jq '.jobs[] | select(.started_at != null and .conclusion != "skipped")
        | {label: (.labels | join(",")), wait: ((.started_at | fromdate) - (.created_at | fromdate))}'
  done |
  jq -s 'group_by(.label)[] | (map(.wait) | sort) as $w
    | {label: .[0].label, jobs: ($w | length), p50: $w[($w | length) / 2 | floor], p90: $w[($w | length) * 0.9 | floor]}'
```

This prints the number of jobs and the p50 and p90 wait in seconds for each runner label over the last 100 completed runs. Run it at the end of a busy weekday, so the sample covers your peak.

### Fix the cause

- **You hit the plan's cap.** Waits grow with the number of jobs in flight. Cut the jobs first: [cancel superseded runs](https://berrybox.io/playbooks/wasted-runs/cancel-stale-runs.md) and [merge tiny jobs](https://berrybox.io/playbooks/critical-path/merge-tiny-jobs.md). Give big scheduled matrices a `strategy.max-parallel` so they leave room for pull request checks. Move work that doesn't need macOS to Linux, since the macOS cap is the smallest. If you still need more, larger runners have their own limit (up to 1,000), and GitHub Support can raise standard limits.
- **A pool hits its maximum.** Raise the runner's maximum concurrency in its autoscaling settings, or split jobs across several runner groups so each has its own limit. VS Code moved its macOS checks from one pool, where jobs still started 14 to 28 minutes late, to three groups.
- **The pool starts cold.** For self-hosted fleets, keep a few idle runners during working hours and make new ones start fast with [prebuilt images](https://berrybox.io/playbooks/slow-setup/prebake-images.md). With Actions Runner Controller, that's a floor in the scale set's Helm values:

```yaml
minRunners: 4
maxRunners: 60
```

Materialize goes further and starts its test agents while the build is still running, so they're ready when the build finishes.

## Keep it safe

- **Runner groups must exist first.** A job whose label or group no runner serves sits in the queue instead of failing, and a self-hosted job stays queued for up to 24 hours before GitHub gives up on it. Create groups and grant the repository access before merging, as VS Code noted for its macOS split.
- **Required checks.** A queued required job blocks merges without showing a failure. Changing `runs-on` keeps check names unless the label is part of the job name.
- **Security.** Keep warm self-hosted runners ephemeral: one job per runner, then destroy it. A reused runner can leak files, credentials and caches into the next job. Don't attach self-hosted runners to public repositories, where fork pull requests could run on them.
- **Caches and images.** A new pool can mean a different image, user or home directory. VS Code's new runners ran as a different user, which changed a cache path, so check cache hits after the move.
- **Cost.** Idle warm runners cost money. Scale the floor down outside working hours, and keep `max-parallel` on scheduled workflows rather than required checks, because it lengthens the run it limits.

## Verify

- Rerun the measurement a week later: p50 and especially p90 wait per label should drop, most visibly at peak hours.
- The affected workflows' p50 and p90 wall time in the [baseline](https://berrybox.io/playbooks/baseline.md) report should fall by about the queue time saved, while job durations stay flat.
- Confirm the same jobs ran and the same checks reported.

## Sources

- Microsoft: [vscode: split macOS pull request checks across three runner groups, each with its own concurrency limit](https://github.com/microsoft/vscode/pull/344796)
- Microsoft: [vscode: move Windows pull request checks off a pool that scaled out slowly at peak hours](https://github.com/microsoft/vscode/pull/343812)
- Materialize: [Materialize blog: provision test agents while the build is still running](https://materialize.com/blog/speeding-up-materialize-ci/). Provisioning test agents while the build still runs cut their preparation time from 4 minutes to 1 minute on average.
- Canva: [Canva Engineering: load caches into new CI agents from EBS snapshots](https://www.canva.dev/blog/engineering/faster-ci-builds-at-canva/). Peak wait for large agents fell from 40 minutes to 10 at P95, and agent startup from 27 minutes to 8.
