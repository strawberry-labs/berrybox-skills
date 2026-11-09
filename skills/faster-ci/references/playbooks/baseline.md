# Measure a CI baseline

Pull recent GitHub Actions history with the gh CLI, find the critical path and the minutes it burns, and keep the numbers you will compare against.

Measure before you change anything. A baseline shows which job decides how long developers wait, where runner minutes go and how noisy the numbers are. Without one, a pull request that claims to speed up CI has nothing to prove itself against.

## What to record

| Metric | Definition | Why it matters |
|---|---|---|
| Wall time | First job queued to last job finished, latest attempt | What a developer waits for. Record the median (p50) and the p90. |
| Queue time | Job created to job started | Time spent waiting for a runner, not running. |
| Runner minutes | Each job's duration rounded up to a whole minute, summed | What GitHub-hosted runners bill. Some plays cut minutes without changing wall time. |
| Critical path | The chain of jobs, linked through `needs`, that ended the run | Only work on this path shortens the run. |
| Long pole | The longest job on the critical path | Usually the first thing worth fixing. |
| Rerun rate | Share of runs on attempt 2 or later | A high rate points at flaky tests or unreliable infrastructure. |
| Required checks | Status checks that branch protection or rulesets require | Every change must keep these reporting under the same names. |

Keep pull request runs separate from default-branch runs. They often run different jobs, and pull request wall time is the number developers feel.

## Run the baseline script

The script below needs Python 3.8 or later and the [GitHub CLI](https://cli.github.com) signed in with read access to the repository (check with `gh auth status`). It only reads: every call is a `gh api` GET request. Save it outside the repository, for example as `/tmp/ci_baseline.py`, and run it from the repository root:

```bash
python3 /tmp/ci_baseline.py --days 30 --max-runs 300 --json /tmp/ci-baseline.json
```

It prints a Markdown report with wall time, queue time, runner minutes and reruns for each workflow and event; the most common critical path and long pole; the slowest jobs; and the slowest steps inside each long pole. `--json` saves the per-run numbers for the comparison at the end. Busy repositories reach the `--max-runs` cap quickly, so raise it or shorten `--days` until the sample holds at least 20 runs of each workflow you care about.

```python
#!/usr/bin/env python3
"""Measure a GitHub Actions baseline with the gh CLI and print a Markdown report.

Read-only: it only calls GitHub's REST API through `gh api`. Python 3.8+, stdlib only.

    python3 ci_baseline.py                 # repository in the current directory, last 30 days
    python3 ci_baseline.py --days 14 --max-runs 200 --repo owner/name
    python3 ci_baseline.py --json baseline.json   # also save the raw numbers
    python3 ci_baseline.py --branch my-branch --days 3  # just one branch's runs, to compare with the baseline

Definitions:
  wall time       first job queued -> last job finished, latest attempt (what a developer waits for)
  queue time      job created -> job started (waiting for a runner)
  runner minutes  each job's duration rounded up to a whole minute, summed (how GitHub bills hosted runners)
  critical path   the chain of jobs, linked through `needs`, that ended the run
  long pole       the longest job on the critical path; jobs off the path don't shorten the run
  rerun           a run whose latest attempt is 2 or higher
"""
import argparse
import json
import urllib.parse
import math
import shutil
import statistics
import subprocess
import sys
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone


def gh(path):
    result = subprocess.run(["gh", "api", path], capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"gh api {path}: {result.stderr.strip()}")
    return json.loads(result.stdout)


def ts(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00")) if value else None


def pct(values, q):
    values = sorted(values)
    if not values:
        return None
    return values[min(len(values) - 1, math.ceil(q * len(values)) - 1)]


def fmt(seconds):
    if seconds is None:
        return "-"
    seconds = int(round(seconds))
    return f"{seconds // 60}m{seconds % 60:02d}s" if seconds >= 60 else f"{seconds}s"


def cell(text):
    return str(text).replace("|", "\\|")


def required_checks(repo, branch):
    names = set()
    try:
        for rule in gh(f"repos/{repo}/rules/branches/{branch}"):
            if rule.get("type") == "required_status_checks":
                for check in rule["parameters"]["required_status_checks"]:
                    names.add(check["context"])
    except RuntimeError:
        pass
    try:
        protection = gh(f"repos/{repo}/branches/{branch}/protection/required_status_checks")
        names.update(protection.get("contexts", []))
    except RuntimeError:
        pass
    return sorted(names)


def run_jobs(repo, run_id):
    jobs, page = [], 1
    while True:
        data = gh(f"repos/{repo}/actions/runs/{run_id}/jobs?per_page=100&page={page}")
        jobs += data["jobs"]
        if len(jobs) >= data["total_count"] or not data["jobs"] or page == 5:
            return jobs
        page += 1


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--repo", help="owner/name (default: the repository in the current directory)")
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--max-runs", type=int, default=300)
    parser.add_argument("--branch", help="only runs for this head branch")
    parser.add_argument("--event", help="only runs for this event, such as pull_request or push")
    parser.add_argument("--json", help="also write the per-run numbers to this file")
    args = parser.parse_args()

    if not shutil.which("gh"):
        sys.exit("The GitHub CLI (gh) is not installed. Install it from https://cli.github.com and run `gh auth login`.")
    info = json.loads(subprocess.run(
        ["gh", "repo", "view", *([args.repo] if args.repo else []), "--json", "nameWithOwner,defaultBranchRef"],
        capture_output=True, text=True, check=True).stdout)
    repo, branch = info["nameWithOwner"], info["defaultBranchRef"]["name"]
    since = (datetime.now(timezone.utc) - timedelta(days=args.days)).date().isoformat()

    query = {"status": "completed", "per_page": 100, "created": f">={since}"}
    query.update({key: getattr(args, key) for key in ("branch", "event") if getattr(args, key)})
    runs, page = [], 1
    while len(runs) < args.max_runs:
        data = gh(f"repos/{repo}/actions/runs?{urllib.parse.urlencode({**query, 'page': page})}")
        runs += data["workflow_runs"]
        if len(data["workflow_runs"]) < 100:
            break
        page += 1
    runs = runs[: args.max_runs]
    if not runs:
        sys.exit(f"No completed workflow runs in {repo} since {since} matching the filters.")

    with ThreadPoolExecutor(8) as pool:
        all_jobs = list(pool.map(lambda run: run_jobs(repo, run["id"]), runs))

    rows = []
    for run, jobs in zip(runs, all_jobs):
        ran = [job for job in jobs if job.get("started_at") and job.get("completed_at") and job["conclusion"] != "skipped"]
        if not ran:
            continue
        created = min(ts(job["created_at"]) for job in ran)
        finished = max(ts(job["completed_at"]) for job in ran)
        # GitHub creates a job when its `needs` finish, so walk back from the
        # last job to the job that released it to recover the critical path.
        chain = [max(ran, key=lambda job: ts(job["completed_at"]))]
        while True:
            released = ts(chain[-1]["created_at"])
            before = [job for job in ran if job not in chain
                      and timedelta(seconds=-10) <= ts(job["completed_at"]) - released <= timedelta(seconds=2)]
            if not before:
                break
            chain.append(max(before, key=lambda job: ts(job["completed_at"])))
        chain.reverse()
        longest = max(chain, key=lambda job: ts(job["completed_at"]) - ts(job["started_at"]))
        rows.append({
            "id": run["id"],
            "workflow": run["name"],
            "event": run["event"],
            "branch": run["head_branch"],
            "conclusion": run["conclusion"],
            "attempt": run.get("run_attempt", 1),
            "wall": (finished - created).total_seconds(),
            "minutes": sum(math.ceil((ts(job["completed_at"]) - ts(job["started_at"])).total_seconds() / 60) for job in ran),
            "critical_path": [job["name"] for job in chain],
            "long_pole": longest["name"],
            "jobs": [{
                "name": job["name"],
                "queue": max(0.0, (ts(job["started_at"]) - ts(job["created_at"])).total_seconds()),
                "duration": (ts(job["completed_at"]) - ts(job["started_at"])).total_seconds(),
                "labels": ",".join(job.get("labels") or []),
                "steps": [{
                    "name": step["name"],
                    "duration": (ts(step["completed_at"]) - ts(step["started_at"])).total_seconds(),
                } for step in job.get("steps") or [] if step.get("started_at") and step.get("completed_at")],
            } for job in ran],
        })

    out = [f"# CI baseline: {repo}", ""]
    scope = "".join(f", {key} `{getattr(args, key)}`" for key in ("branch", "event") if getattr(args, key))
    out.append(f"Window: completed runs since {since} ({args.days} days{scope}). Sampled {len(rows)} runs"
               f"{' (capped by --max-runs)' if len(runs) == args.max_runs else ''}. Default branch: `{branch}`.")
    checks = required_checks(repo, branch)
    out.append("Required checks on the default branch: " + (", ".join(f"`{name}`" for name in checks) if checks
               else "none found, or not visible to this token. Check branch protection and rulesets before renaming jobs."))
    out += ["", "## Workflows", "",
            "| Workflow | Event | Runs | Success | Cancelled | p50 wall | p90 wall | p50 queue | Runner min/run (p50) | Reruns |",
            "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
    groups = defaultdict(list)
    for row in rows:
        groups[(row["workflow"], row["event"])].append(row)
    ordered = sorted(groups.items(), key=lambda item: -sum(row["minutes"] for row in item[1]))
    for (workflow, event), items in ordered:
        finished = [row for row in items if row["conclusion"] in ("success", "failure")]
        queues = [job["queue"] for row in items for job in row["jobs"]]
        out.append("| {} | {} | {} | {:.0%} | {} | {} | {} | {} | {} | {:.0%} |".format(
            cell(workflow), event, len(items),
            sum(row["conclusion"] == "success" for row in items) / len(items),
            sum(row["conclusion"] == "cancelled" for row in items),
            fmt(pct([row["wall"] for row in finished], 0.5)), fmt(pct([row["wall"] for row in finished], 0.9)),
            fmt(pct(queues, 0.5)), pct([row["minutes"] for row in items], 0.5),
            sum(row["attempt"] > 1 for row in items) / len(items)))

    out += ["", "## Critical paths", "",
            "The chain of jobs that ended each run, and the longest job on it (the long pole). Speeding up jobs off this path does not shorten the run.", "",
            "| Workflow | Event | Most common critical path | Long-pole job | Share of runs | p50 long-pole duration |",
            "|---|---|---|---|---:|---:|"]
    poles = []
    for (workflow, event), items in ordered[:12]:
        name, count = Counter(row["long_pole"] for row in items).most_common(1)[0]
        path = Counter(" → ".join(row["critical_path"]) for row in items).most_common(1)[0][0]
        durations = [job["duration"] for row in items for job in row["jobs"] if job["name"] == name]
        poles.append((workflow, name))
        out.append(f"| {cell(workflow)} | {event} | {cell(path)} | {cell(name)} | {count / len(items):.0%} | {fmt(pct(durations, 0.5))} |")

    out += ["", "## Slowest jobs", "", "| Workflow | Job | Runs | p50 duration | p90 duration | p50 queue | Runner labels |",
            "|---|---|---:|---:|---:|---:|---|"]
    jobs_by_name = defaultdict(list)
    for row in rows:
        for job in row["jobs"]:
            jobs_by_name[(row["workflow"], job["name"])].append(job)
    slowest = sorted(jobs_by_name.items(), key=lambda item: -statistics.median(job["duration"] for job in item[1]))
    for (workflow, name), items in slowest[:15]:
        out.append("| {} | {} | {} | {} | {} | {} | {} |".format(
            cell(workflow), cell(name), len(items), fmt(pct([job["duration"] for job in items], 0.5)),
            fmt(pct([job["duration"] for job in items], 0.9)), fmt(pct([job["queue"] for job in items], 0.5)),
            cell(Counter(job["labels"] for job in items).most_common(1)[0][0])))

    out += ["", "## Steps inside the long-pole jobs", "", "| Workflow | Job | Step | p50 | p90 | Share of job |", "|---|---|---|---:|---:|---:|"]
    seen = set()
    for workflow, name in poles:
        if (workflow, name) in seen:
            continue
        seen.add((workflow, name))
        jobs = jobs_by_name[(workflow, name)]
        steps = defaultdict(list)
        for job in jobs:
            for step in job["steps"]:
                steps[step["name"]].append(step["duration"])
        job_p50 = pct([job["duration"] for job in jobs], 0.5) or 1
        for step, durations in sorted(steps.items(), key=lambda item: -statistics.median(item[1]))[:6]:
            p50 = pct(durations, 0.5)
            out.append(f"| {cell(workflow)} | {cell(name)} | {cell(step)} | {fmt(p50)} | {fmt(pct(durations, 0.9))} | {p50 / job_p50:.0%} |")

    total = sum(row["minutes"] for row in rows)
    out += ["", "## Totals", "",
            f"- Runner minutes across sampled runs: {total} (about {total * 7 / max(args.days, 1):.0f} per week if the sample covers the whole window).",
            f"- Reruns: {sum(row['attempt'] > 1 for row in rows)} of {len(rows)} runs. Cancelled: {sum(row['conclusion'] == 'cancelled' for row in rows)}.",
            "- Treat single runs as noisy: compare medians from five or more runs of the same workflow and event."]
    print("\n".join(out))
    if args.json:
        with open(args.json, "w") as handle:
            json.dump({"repo": repo, "since": since, "required_checks": checks, "runs": rows}, handle, indent=1)


if __name__ == "__main__":
    main()
```

The same script ships in the `faster-ci` agent skill: `npx skills add strawberry-labs/berrybox-skills`.

## Without Python

The raw data takes a few `gh api` calls. `gh` fills in `{owner}` and `{repo}` from the repository in the current directory; replace `YYYY-MM-DD`, `RUN_ID` and `main` with your values.

```bash
# Repository and default branch
gh repo view --json nameWithOwner,defaultBranchRef

# Completed runs since a date. Repeat with &page=2, 3, ... until a page returns fewer than 100.
gh api "repos/{owner}/{repo}/actions/runs?status=completed&per_page=100&created=%3E%3DYYYY-MM-DD" \
  --jq '.workflow_runs[] | [.id, .name, .event, .conclusion, .run_attempt, .created_at] | @tsv'

# Jobs for one run, with the timestamps you need for queue time, duration and the critical path
gh api "repos/{owner}/{repo}/actions/runs/RUN_ID/jobs?per_page=100" \
  --jq '.jobs[] | [.name, .created_at, .started_at, .completed_at, .conclusion, (.labels | join(","))] | @tsv'

# Required checks from rulesets, then from classic branch protection
gh api "repos/{owner}/{repo}/rules/branches/main" \
  --jq '.[] | select(.type == "required_status_checks") | .parameters.required_status_checks[].context'
gh api "repos/{owner}/{repo}/branches/main/protection/required_status_checks" --jq '.contexts[]'
```

GitHub creates a job when the jobs in its `needs` finish, so a job's `created_at` matches the moment its last dependency completed. Start from the job that finished last and keep stepping back to the job that completed just before the current job was created: that chain is the critical path.

## Read the report

Match what you see to a playbook:

| What the baseline shows | Start with |
|---|---|
| Runs cancelled by newer pushes, duplicate push and pull request runs, or full runs for docs-only changes | [Wasted runs](https://berrybox.io/playbooks/wasted-runs.md) |
| Checkout, dependency install, cache restore or toolchain setup takes a large share of the long pole | [Slow setup](https://berrybox.io/playbooks/slow-setup.md) |
| Compile, bundle, Docker build, lint or type-check steps dominate the long pole | [Slow builds](https://berrybox.io/playbooks/slow-builds.md) |
| A test job is the long pole | [Slow tests](https://berrybox.io/playbooks/slow-tests.md) |
| Every change runs the whole suite in a large repository or monorepo | [Test selection](https://berrybox.io/playbooks/test-selection.md) |
| Jobs wait on `needs` they don't use, or several jobs build the same thing | [Critical path](https://berrybox.io/playbooks/critical-path.md) |
| Median queue time above about 30 seconds, or CPU-bound jobs on small runners | [Runners](https://berrybox.io/playbooks/runners.md) |
| A rerun rate above a few percent, or failures that pass on retry | [Flaky tests](https://berrybox.io/playbooks/flaky-tests.md) |
| Merges wait on long gates, or pull request volume keeps runners saturated | [PR volume](https://berrybox.io/playbooks/pr-volume.md) |

## Compare after a change

Keep the report out of the repository: put it in the pull request description or your notes. After a change, compare the same workflow and event. A single pull request run is one sample, and run-to-run noise of 10 to 20 percent is common, so:

- measure only the branch's runs with `python3 /tmp/ci_baseline.py --branch YOUR-BRANCH --days 3`, then compare the job or step the play targets as well as total wall time;
- rerun the changed workflow two or three times when minutes allow (`gh run rerun RUN_ID`) and compare medians;
- report runner minutes as well as wall time, because some plays save one and not the other;
- label every number you did not measure as an estimate.
