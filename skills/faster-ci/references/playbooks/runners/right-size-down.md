# Run light jobs on the smallest runner that fits

Move short, single-threaded jobs such as lint, format, labeling and gate checks to the smallest runner that keeps their wall time, such as GitHub's 1-vCPU ubuntu-slim, and confirm with an A/B run on the same commit.

- Playbook: [Give the long pole the right machine](https://berrybox.io/playbooks/runners.md)
- Saves: runner minutes
- Risk: low
- Web page: https://berrybox.io/playbooks/runners/right-size-down

## Signals in your baseline

- Jobs with a p50 under one or two minutes run on 4-, 8- or 16-core runners.
- Jobs that only lint, format, label, comment, check metadata or call an API run on the same runner label as builds.
- Single-threaded tools (formatters, workflow linters, license or changelog checks) never install dependencies or compile.
- Runner minutes are paid, as in private repositories or on larger and third-party runners.

## Why it works

Runner prices scale with size, but a formatter, a workflow linter or a job that posts a comment uses one core and little memory. On a larger runner, the extra cores sit idle while you pay for them. GitHub-hosted runners also bill each job rounded up to a whole minute, so a 20-second job on an 8-core runner pays a full minute at the 8-core rate. Moving those jobs to the smallest runner that keeps their wall time cuts the bill without slowing anything a developer waits for.

On GitHub-hosted runners the smallest option is `ubuntu-slim`: 1 vCPU, 5 GB of RAM and 14 GB of disk, x64 only, running as a container instead of a full VM, at a third of the standard 2-core Linux price. Standard runners are free in public repositories, so the savings come in private repositories and on paid runners.

## Apply it

### Pick the candidates

From the [baseline](https://berrybox.io/playbooks/baseline.md)'s `--json` output, which records every job's duration and runner labels, list jobs whose p50 is under a minute or two. Keep the ones that:

- run one single-threaded tool, or only call APIs;
- install nothing, or only a small pinned tool;
- don't use Docker in any form: no `container:`, no `services:`, no container actions and no `docker` commands;
- never come close to 15 minutes.

Leave anything that compiles, runs `npm ci` or `pnpm install`, or runs tests in parallel. Those steps use every core they get, so a smaller runner makes them slower.

### Move them

```yaml
jobs:
  pr-title:
    if: github.event_name == 'pull_request'
    runs-on: ubuntu-slim
    timeout-minutes: 5
    steps:
      - name: Check the pull request title
        env:
          TITLE: ${{ github.event.pull_request.title }}
        run: |
          if ! grep -Eq '^(feat|fix|docs|chore|ci|refactor|test|perf)(\(.+\))?!?: ' <<<"$TITLE"; then
            echo "::error::Use a Conventional Commits title, such as 'fix(api): handle an empty body'"
            exit 1
          fi
```

- `timeout-minutes: 5` fails a stuck job well before slim's 15-minute hard limit.
- The title goes through `env`, not straight into the script, so a crafted title can't inject shell commands.
- The image has Bash, Git, curl, jq, the GitHub CLI, Python, pipx and Node, but no Rust, Go or Java toolchain, and it can't run Docker containers. Check the [ubuntu-slim image README](https://github.com/actions/runner-images/blob/main/images/ubuntu-slim/ubuntu-slim-Readme.md) before you move a job.

On larger, third-party or self-hosted runners, the same play means stepping down a size: from 8 to 4 vCPU, or from 4 to 2, for jobs that don't use the cores. Self-hosted fleets can size disks the same way: Webflow logged disk use after each job and found many of its CI volumes could be cut by about half.

### Measure before you merge

Run the moved job and the original on the same commit, two or three times each, as in [the bigger-runner benchmark](https://berrybox.io/playbooks/runners/bigger-runner.md). Compare median duration and cost per run (billed minutes times the rate). Keep the move if wall time stays about the same.

## Keep it safe

- **Missing tools cost time.** A job that has to install its toolchain first can end up slower than before. Actix's `fmt` job took 31 and 47 seconds in its first runs on `ubuntu-slim`, against a historical median of 17, since slim has no Rust toolchain and the job installs one. It may still be cheaper, but check that it isn't on the critical path.
- **Hard limits.** Slim jobs are terminated and fail at 15 minutes, and 5 GB of RAM can run out for type checkers and bundlers. Jobs that need Docker, privileged operations or file system mounts fail there.
- **Concurrency.** `ubuntu-slim` follows the same plan-based concurrency limits as other standard runners, so don't count on it for extra capacity.
- **Required checks.** Changing `runs-on` keeps the check name unless the runner label is part of it, such as a matrix job named `lint (ubuntu-latest)`. Update branch protection in the same change if it is.
- **Security.** Moving a job doesn't change its permissions or secrets. Keep untrusted input like titles and branch names in `env`, as above.

## Verify

- After a week, compare each moved job's p50 and p90 duration with the baseline, and check that none hit its timeout.
- Compare cost per run for those jobs, using billed minutes and the new rate.
- Confirm the same checks reported and passed, with the same check names.

## Sources

- gitoxide: [gitoxide: move fast, single-threaded jobs that use no Docker to ubuntu-slim](https://github.com/GitoxideLabs/gitoxide/pull/2386)
- Actix: [actix-web: run the zizmor and fmt lint jobs on ubuntu-slim and keep compile jobs where they were](https://github.com/actix/actix-web/pull/4380)
- Webflow: [Webflow blog: shrink over-provisioned CI disk volumes using disk usage logged after each job](https://webflow.com/blog/how-webflow-cut-ci-costs-by-a-third)
