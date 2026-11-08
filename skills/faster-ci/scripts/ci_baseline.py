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
