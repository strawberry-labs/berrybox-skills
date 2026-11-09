# Keep CI ahead of a growing pull request queue

When people and coding agents open more pull requests than CI can absorb, test merges together in a queue, keep the required gate short and catch cheap failures before they reach a runner.

Web page: https://berrybox.io/playbooks/pr-volume

## Signals in your baseline

- Branch protection requires branches to be up to date, so every merge sends other ready pull requests back to update and rerun CI.
- The default branch breaks after merges that each passed CI on their own.
- The required checks include the slowest suites, so every merge waits on them.
- Many failed pull_request runs fail in lint, format or type-check steps.
- Pull requests opened by coding agents fail their first run and collect fix-up pushes.

More pull requests mean more runs per hour, more results that go stale before anyone merges and more pairs of changes that pass alone but break together. Coding agents push all three up: they open pull requests quickly, push many small fixes and read CI output to decide what to do next. These plays keep the merge path short and correct as volume grows.

## Confirm it in your baseline

- Check whether merges must be up to date: `gh api "repos/{owner}/{repo}/rules/branches/main" --jq '.[] | select(.type == "required_status_checks") | .parameters.strict_required_status_checks_policy'`, or `.strict` from the branch protection endpoint in the [baseline](https://berrybox.io/playbooks/baseline.md) guide.
- Find the required checks in the report and compare their workflow's p90 wall time with the fastest workflows. A 30-minute required suite sets the pace for every merge.
- Open the last 20 failed `pull_request` runs (`gh run list --event pull_request --status failure --limit 20`) and note the first step that failed in each. Count how many were lint, format or type checks.
- For pull requests opened by agents, count pushes and failed runs before the first green run.

## Order of work

Start with [check before push](https://berrybox.io/playbooks/pr-volume/check-before-push.md) and [agent-readable output](https://berrybox.io/playbooks/pr-volume/agent-readable-output.md): they're cheap, change nothing about what is required and cut failed runs. Next, [keep required checks minimal](https://berrybox.io/playbooks/pr-volume/minimal-required-checks.md), so the gate every merge waits on is short. Add a [merge queue](https://berrybox.io/playbooks/pr-volume/merge-queue.md) once that gate is fast and reliable, because a slow or flaky gate makes the queue slow too. If agents open pull requests, have them [verify before opening one](https://berrybox.io/playbooks/pr-volume/verify-before-pr.md).

## Plays

- [Use a merge queue instead of requiring up-to-date branches](https://berrybox.io/playbooks/pr-volume/merge-queue.md): A merge queue tests each ready pull request on top of the base branch and the pull requests ahead of it, so authors stop updating branches and rerunning CI before every merge. Required workflows must also run on merge_group. Saves wait time and runner minutes; medium risk.
- [Keep required checks fast and run heavy suites after merge](https://berrybox.io/playbooks/pr-volume/minimal-required-checks.md): Every merge waits on the slowest required check. Require only fast, reliable checks on pull requests, and run the slow suites in the merge queue, on the default branch after merge or as optional pull request jobs. Saves wait time and runner minutes; medium risk.
- [Catch lint, format and type errors before they reach CI](https://berrybox.io/playbooks/pr-volume/check-before-push.md): Run the repository's fast checks in a pre-push hook so lint, format and type failures cost seconds on the author's machine instead of a CI run, and keep the same checks in CI for pushes that skip the hook. Saves wait time and runner minutes; low risk.
- [Make CI failures short and easy for agents to act on](https://berrybox.io/playbooks/pr-volume/agent-readable-output.md): Agents read CI logs to decide what to change. Print failures instead of passes, keep each error on one line with its file and reason, and save the full output as an artifact, so the cause fits in the agent's context. Saves wait time and runner minutes; low risk.
- [Have coding agents run the checks before they open a pull request](https://berrybox.io/playbooks/pr-volume/verify-before-pr.md): Give agents one command that runs what CI requires, make them pass it before opening or updating a pull request, and cap CI rounds, so agent pull requests arrive green instead of using CI as a test runner. Saves wait time and runner minutes; low risk.
