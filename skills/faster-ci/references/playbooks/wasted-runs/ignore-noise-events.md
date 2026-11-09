# Don't start a runner for comments, labels and edits your jobs ignore

Comment, label, review and description-edit events can start full workflow runs and cancel real ones. Keep them out of the workflow that reports required checks, and gate the workflows that need them with job-level conditions.

- Playbook: [Stop paying for runs nobody needs](https://berrybox.io/playbooks/wasted-runs.md)
- Saves: runner minutes
- Risk: medium
- Web page: https://berrybox.io/playbooks/wasted-runs/ignore-noise-events

## Signals in your baseline

- A workflow listens to issue_comment, pull_request_review or pull_request_review_comment, or lists labeled, unlabeled or edited in its pull_request types.
- `gh run list --json workflowName,event,headSha` shows more pull_request runs of one workflow than distinct head commits.
- Jobs read the comment text, label or actor in a step and exit early, so many runs last a minute or less.
- Runs end cancelled although no newer commit was pushed, because a label or comment run in the same concurrency group replaced them.

## Why it works

Every event listed under `on:` creates a workflow run. A triage bot adding labels, a review bot posting comments, someone fixing a typo in the description: on an active pull request these events can outnumber pushes. A job with no condition takes a runner, checks out and installs before it can find out there was nothing to do. A job-level `if` is evaluated before any runner is assigned, so a false condition costs nothing, and an event left out of `on:` doesn't create a run at all.

Minutes aren't the only cost. A run started by a noise event joins the workflow's concurrency group, so with `cancel-in-progress` it can cancel the run that was testing the latest push. And when a label or edit event reruns a pull request workflow and every job skips, the skipped jobs report success under the same check names on the pull request's head commit.

## Apply it

Find the workflows that run more than once per commit. Ignore `schedule` rows, which always reuse one commit:

```bash
gh run list --limit 500 --json workflowName,event,headSha --jq '
  group_by([.workflowName, .event])
  | map({workflow: .[0].workflowName, event: .[0].event, runs: length,
         commits: (map(.headSha) | unique | length)})
  | .[] | select(.runs > .commits)
  | "\(.workflow) | \(.event) | \(.runs) runs | \(.commits) commits"'
```

Keep the workflow that reports required checks on events that change code:

```yaml
on:
  pull_request:
    types: [opened, synchronize, reopened, ready_for_review]
```

Move jobs that react to titles, labels or descriptions, such as title linting, into their own workflow, under job names that no required check uses.

### Label-gated workflows

For an expensive job that people opt into with a label:

```yaml
name: Benchmarks

on:
  pull_request:
    types: [opened, reopened, ready_for_review, synchronize]

permissions:
  contents: read

jobs:
  bench:
    # Runs when a pull request opens or becomes ready. Later pushes run it
    # only while the pull request carries the "benchmark" label.
    if: >-
      github.event.pull_request.draft == false &&
      (github.event.action != 'synchronize' ||
       contains(github.event.pull_request.labels.*.name, 'benchmark'))
    concurrency:
      group: bench-${{ github.event.pull_request.number }}
      cancel-in-progress: true
    runs-on: ubuntu-latest
    timeout-minutes: 30
    steps:
      - uses: actions/checkout@v7
      - run: make bench
```

- `labeled` is left out of `types` on purpose. A bot that rewrites labels on each review round would start a run per label. Once the label is on, the next push runs the job.
- `concurrency` sits on the job. A run whose job is skipped never enters the group, so it can't cancel a run in progress.
- `labels.*.name` reads the labels from the event payload, with no API call.

### Comment commands

Gate the command job on the exact text and on who wrote it:

```yaml
on:
  issue_comment:
    types: [created]

jobs:
  preview:
    if: >-
      github.event.issue.pull_request &&
      github.event.comment.body == '/preview' &&
      contains(fromJSON('["OWNER", "MEMBER", "COLLABORATOR"]'), github.event.comment.author_association)
```

- `issue_comment` fires for every comment on every issue and pull request, bots included. The `if` drops all but the exact command before a runner starts. String comparisons in expressions ignore case.
- `author_association` limits the command to people with access to the repository.

## Keep it safe

- Don't listen to `labeled`, `edited` or review events in the workflow that reports required checks and then skip its jobs. The skipped jobs report success under the required names on the head commit and can stand in for a failure from the last real run. If one workflow must handle both, give the skipped jobs different names for those events, as OpenAI did for description edits.
- With workflow-level `cancel-in-progress`, any run in the group cancels the one in progress. Put `concurrency` on the gated job, or add `github.event_name` and the action to the group key.
- `issue_comment` runs use the workflow from the default branch and get the repository's secrets, without the read-only token that fork pull requests get. Never check out and run the pull request's code in them.
- Checks from `issue_comment` runs attach to the default branch's latest commit, not to the pull request, so they can't satisfy a required check. Use comment commands for optional extras.

## Verify

- On a test pull request, add a label, edit the description and post an ordinary comment. The CI workflow should start no new runs, and gated workflows should finish as skipped within seconds.
- Push a commit. CI should run once and finish without being cancelled by anything but a newer push.
- After a week, rerun the [baseline](https://berrybox.io/playbooks/baseline.md) and the query above. Rows where runs exceed commits should be gone or close to it, and runner minutes per pull request should fall.

## Sources

- OpenAI: [codex-security: skip source checks for body-only pull request edits, in a separate concurrency group and under distinct check names](https://github.com/openai/codex-security/pull/1708)
- assistant-ui: [assistant-ui: run the performance job on open and ready, on later pushes only with a label, and move concurrency onto the job](https://github.com/assistant-ui/assistant-ui/pull/7237)
