# Give the long pole the right machine

Cut the time jobs wait for a runner, benchmark CPU-bound long poles on more cores, move disk-heavy steps to faster storage and put light jobs on the smallest runner that fits, judging each change by wall time and cost per run.

Web page: https://berrybox.io/playbooks/runners

## Signals in your baseline

- Median queue time above about 30 seconds for a runner label, or a p90 measured in minutes.
- The long-pole job compiles or runs parallel tests on a 2- or 4-vCPU runner.
- Extracting archives, installing packages or writing many small files takes minutes, especially on Windows.
- Lint, format and gate jobs that finish in under two minutes run on the same large runners as the builds.

The other playbooks make jobs do less. These change the machine underneath: how long a job waits for one, how many cores and how fast a disk it gets, and what each minute costs. A bigger runner usually costs more per minute, so every play here compares wall time and cost per run on the same commit before you switch.

## Confirm it in your baseline

- Read **p50 queue** in the **Slowest jobs** table next to **Runner labels**. A label whose median wait is above about 30 seconds, or whose waits climb at busy hours, needs [less queue time](https://berrybox.io/playbooks/runners/cut-queue-time.md) before anything else.
- For the long pole, read its runner label and its rows in **Steps inside the long-pole jobs**. Compile, type-check and parallel test steps scale with cores. Unpacking, `node_modules` installs and database-heavy tests usually depend on the disk.
- Find short jobs in the baseline's `--json` output, which lists every job with its duration and runner labels: a p50 under a minute or two on a 4-, 8- or 16-core runner pays for cores it never uses.
- Check `runs-on` in the workflow files for labels served by a small pool or a low concurrency limit, such as macOS or a larger runner with a small maximum.

## Order of work

Fix queue time first when it's high: it adds straight to wall time, and no amount of CPU wins it back. Then [benchmark the long pole on bigger runners](https://berrybox.io/playbooks/runners/bigger-runner.md), because that's where most of the wall-time gain is, and the bill changes with it. Use [faster disks](https://berrybox.io/playbooks/runners/fast-disk.md) when the long pole is IO-bound. [Right-sizing light jobs down](https://berrybox.io/playbooks/runners/right-size-down.md) is low risk at any point and often pays for the bigger long-pole runner.

## Plays

- [Benchmark the long pole on a bigger runner](https://berrybox.io/playbooks/runners/bigger-runner.md): Run the same long-pole job on the same commit at two or three runner sizes, two or three times each, and switch only when the wall-time gain is worth the change in cost per run. Saves wait time; medium risk.
- [Cut the time jobs wait for a runner](https://berrybox.io/playbooks/runners/cut-queue-time.md): Measure queue time per runner label, find out whether a concurrency cap, a cold pool or a burst of jobs causes it, and fix that cause with higher limits, split runner groups, warm capacity or fewer jobs. Saves wait time; medium risk.
- [Move IO-heavy work onto faster storage](https://berrybox.io/playbooks/runners/fast-disk.md): When unpacking, installing or database writes dominate a job, put the workspace, package caches, build outputs and test data on the fastest storage the runner has, such as a Windows Dev Drive, a local NVMe disk or tmpfs. Saves wait time and runner minutes; medium risk.
- [Run light jobs on the smallest runner that fits](https://berrybox.io/playbooks/runners/right-size-down.md): Move short, single-threaded jobs such as lint, format, labeling and gate checks to the smallest runner that keeps their wall time, such as GitHub's 1-vCPU ubuntu-slim, and confirm with an A/B run on the same commit. Saves runner minutes; low risk.
