# Run a reduced matrix on pull requests and the full matrix later

Test pull requests on the few platforms and versions that catch most breakage, run every combination in the merge queue, on the default branch or on a schedule, and require one aggregate check so the legs can change.

- Playbook: [Shorten the path that ends the run](https://berrybox.io/playbooks/critical-path.md)
- Saves: wait time and runner minutes
- Risk: medium
- Web page: https://berrybox.io/playbooks/critical-path/trim-the-matrix

## Signals in your baseline

- Pull request runs expand a matrix of three or more operating systems or runtime versions.
- In recent runs, the legs of the matrix almost always pass or fail together.
- A macOS or Windows leg is the "Long-pole job" for pull request runs, or the matrix legs make up most of "Runner min/run".

## Why it works

A matrix multiplies a job by every combination of its axes: three operating systems and four language versions make 12 jobs on every push. On most pull requests, a bug that breaks one leg breaks all of them, so the extra legs repeat a result you already have. Bugs that show up on only one platform or version are real but rare, and catching them in the merge queue, on the default branch or overnight is usually soon enough.

So pick the matrix from the event. Pull requests get the few legs that catch most breakage, typically the oldest and newest supported versions on Linux. The merge queue, pushes to the default branch and a nightly schedule get every combination, so coverage moves later instead of disappearing.

## Apply it

```yaml
name: Test
on:
  pull_request:
  merge_group:
  push:
    branches: [main]
  schedule:
    - cron: "17 3 * * *"

permissions:
  contents: read

jobs:
  test:
    runs-on: ${{ matrix.os }}
    strategy:
      fail-fast: false
      matrix:
        os: ${{ github.event_name == 'pull_request' && fromJSON('["ubuntu-latest"]') || fromJSON('["ubuntu-latest", "macos-latest", "windows-latest"]') }}
        python: ${{ github.event_name == 'pull_request' && fromJSON('["3.11", "3.14"]') || fromJSON('["3.11", "3.12", "3.13", "3.14"]') }}
    steps:
      - uses: actions/checkout@v7
      - uses: actions/setup-python@v7
        with:
          python-version: ${{ matrix.python }}
      - run: pip install -e ".[test]"
      - run: pytest

  test-ok:
    if: always()
    needs: test
    runs-on: ubuntu-latest
    steps:
      - name: Fail unless every leg passed
        run: test "${{ needs.test.result }}" = success
```

- The `&&` and `||` pick the short list for `pull_request` events and the full list for every other event. `fromJSON` turns each string into an array.
- `merge_group` gives the merge queue the full matrix, so nothing lands without it. Without a merge queue, the `push` run on `main` and the nightly `schedule` catch platform-only failures soon after the merge.
- `test-ok` is the only check to require. Leg names such as `test (macos-latest, 3.12)` stop appearing on pull requests, and a required check that never reports blocks every merge.
- `needs.test.result` is `success` only when every leg passed.

For pull requests that touch platform-specific code, let authors ask for the full matrix with a label: add `labeled` to the `pull_request` trigger's `types`, and put `!contains(github.event.pull_request.labels.*.name, 'full-matrix')` next to the event check in both expressions.

## Keep it safe

- Make sure the full matrix still runs and that someone sees its failures. A nightly run that fails without anyone noticing is coverage you've deleted, so send failures to a channel or an issue and treat a red default branch as urgent.
- Scheduled workflows run only on the default branch, and GitHub disables them in public repositories after 60 days without activity.
- A job-level `if` can't drop legs: GitHub evaluates it before it expands the matrix, so it can't read `matrix`. Choose the lists from the event as above, or skip inside steps.
- Keep security checks such as code scanning and dependency review on every pull request, whatever the matrix does.
- Don't release from a commit that hasn't passed the full matrix. Run the full matrix on release tags, or check that the `push` run for the commit passed before publishing.

## Verify

- In the branch baseline, **Runner min/run (p50)** for `pull_request` runs should drop roughly in proportion to the legs removed, and p50 wall falls too if a slow leg was the long pole.
- Check that the full matrix still runs: `gh run list --workflow test.yml --event schedule`, and the `merge_group` or `push` runs, should show every leg.
- Track how often the full matrix fails on something the pull request run passed. If one leg keeps catching problems, add it back to the pull request matrix.

## Sources

- Slack: [Slack Engineering: run a small set of end-to-end tests before merge, more after merge and the rest every two hours](https://slack.engineering/balancing-safety-and-velocity-in-ci-cd-at-slack/). Test turnaround time (p95) decreased over 40% and is consistently below 18 minutes, with no measurable increase in defects reported by customers.
- OpenAI: [codex: keep quick Cargo checks on pull requests and run the heavy Cargo matrix after merging or on demand](https://github.com/openai/codex/pull/16072)
- Shopify: [tecnix: run the VM, installer and flake suites on main, in the merge queue and on demand rather than on every pull request](https://github.com/Shopify/tecnix/pull/74)
- DoorDash: [agentic-orchestrator: run the full suite on Ubuntu and a smoke subset on macOS and ARM](https://github.com/doordash-oss/agentic-orchestrator/pull/139)
