# Benchmark the long pole on a bigger runner

Run the same long-pole job on the same commit at two or three runner sizes, two or three times each, and switch only when the wall-time gain is worth the change in cost per run.

- Playbook: [Give the long pole the right machine](https://berrybox.io/playbooks/runners.md)
- Saves: wait time
- Risk: medium
- Web page: https://berrybox.io/playbooks/runners/bigger-runner

## Signals in your baseline

- The long-pole job runs on a 2- or 4-vCPU runner and spends most of its time compiling, type-checking or running tests.
- The job's tools already run work in parallel (build workers, -j, test workers), so extra cores would have work to do.
- Jobs hit memory limits, such as out-of-memory kills, "JavaScript heap out of memory" or a test runner capped to fit 8 GB.
- Optimizing the job's setup and tests has left a long pole that is still mostly CPU time.

## Why it works

A CPU-bound job finishes sooner on more cores only when its tools split the work: compilers with parallel jobs, Cargo, Gradle and Bazel workers, test runners with worker pools, type checkers that build several projects. Memory matters as well. On 8 GB, bundlers, `tsc` and Gradle daemons can swap, crash or limit their own parallelism. Newer CPUs and faster disks help even at the same core count; Linear and Spotify both credit faster hardware for their gains.

The price per minute usually rises about in step with cores. If doubling the cores halves the job's time, cost per run stays flat and the wait halves. If it saves less than half, each run costs more. Every job also has serial parts that more cores can't touch, so gains flatten: OpenMeter's build barely moved from 16 to 32 cores. GitHub-hosted runners also round each job up to a whole minute, which matters for short jobs. You can't predict where your job's curve flattens, so measure it.

## Apply it

### Pick the job and the candidates

Take the long-pole job from your [baseline](https://berrybox.io/playbooks/baseline.md) and pick two or three sizes: the current one, double and quadruple. The options include:

- **GitHub larger runners** (Team and Enterprise Cloud plans): Linux from 2 vCPU and Windows from 4, up to 96, plus larger macOS machines. An organization admin creates them, and you target them by runner name or runner group.
- **Third-party hosted runners**, which you add by installing the provider's GitHub App and changing `runs-on`. BerryBox (berrybox.io), for example, uses labels such as `berrybox-8vcpu-ubuntu-2404`.
- **Self-hosted runners** on hardware you choose, for example with Actions Runner Controller on Kubernetes.

### Benchmark on the same commit

Push a temporary workflow on a branch of its own. It runs the long-pole job's steps unchanged on each candidate, three times each:

```yaml
name: Runner benchmark
on:
  push:
    branches: [runner-benchmark]

jobs:
  bench:
    strategy:
      fail-fast: false
      matrix:
        # Use labels that exist for your account: a larger runner name,
        # a provider label or a self-hosted label.
        runner: [ubuntu-latest, ubuntu-24.04-8core, ubuntu-24.04-16core]
        attempt: [1, 2, 3]
    runs-on: ${{ matrix.runner }}
    timeout-minutes: 60
    steps:
      - uses: actions/checkout@v7
      # Paste the long-pole job's steps here, unchanged.
      - run: make test
```

- A push to the `runner-benchmark` branch runs every matrix job on the same commit. A `workflow_dispatch` trigger would only work once the file is on the default branch.
- `fail-fast: false` keeps one failing size from stopping the others.
- The `attempt` axis gives you three samples per size in one run, so you can compare medians.
- Run it with the job's caches warm, the way pull requests see it.

Then read each job's duration:

```sh
gh run view RUN_ID --json jobs \
  --jq '.jobs[] | "\(.name)\t\((.completedAt | fromdate) - (.startedAt | fromdate))s"'
```

For each size, take the median duration and compute cost per run: minutes, rounded up per job if the provider bills that way, times that runner's per-minute price from the provider's pricing page. Record queue time separately, because a pool that starts cold can hide a fast machine.

### Decide

Pick the size where the next step up stops cutting time by close to half, unless the wait matters more to your team than the extra cost. Switch only the long-pole job, and match its worker counts to the new core count ([match workers to cores](https://berrybox.io/playbooks/slow-tests/match-workers-to-cores.md)). Delete the benchmark branch.

## Keep it safe

- **Images differ.** GitHub's larger runners can use the same images as standard ones. Other providers and self-hosted runners may ship different tools, versions and users. Set up toolchains with setup actions instead of relying on what's preinstalled, and compare test counts.
- **Check names.** Changing `runs-on` keeps the check name unless the runner label appears in it, as in a matrix job named `test (ubuntu-latest)`. Update branch protection in the same change if it does.
- **Labels with no runner.** A job whose label no runner serves waits in the queue instead of failing. Create the runner and grant the repository access before you merge.
- **Security.** Third-party and self-hosted runners see your code and any secrets the job uses. Prefer ephemeral runners that take one job and are destroyed, and never let fork pull requests run on persistent self-hosted runners.
- **Cost.** GitHub's larger runners are not free in public repositories, where standard runners cost nothing. Set a budget before you switch.

## Verify

- Over a few days of pull requests, compare the long pole's p50 and p90 duration and the run's p50 wall time with the baseline.
- Compare cost per run using each job's billed minutes and rate.
- Check queue time on the new label, and confirm the same tests ran and the same checks reported.

## Sources

- Linear: [Linear blog: move CI to third-party runners with faster CPUs, storage and cache](https://linear.app/now/ci-bottleneck-reworked#upgraded-infrastructure-and-tooling). In a like-for-like comparison of the two days either side of the switch, jobs ran 34% faster on average, with tsc dropping 52%.
- OpenMeter: [OpenMeter blog: benchmark the same cached build on runners from 4 to 32 cores](https://openmeter.io/blog/how-we-made-our-ci-pipeline-5x-faster). On one provider's runners, with caching already in place, the build averaged 8.82 minutes on 4 cores, 5.55 on 8, 4.45 on 16 and 4.28 on 32.
- Spotify: [Spotify Engineering: benchmark iOS builds on newer bare-metal Macs before moving pre-merge checks](https://engineering.atspotify.com/2020/05/how-we-gave-superpowers-to-our-macos-ci). For the App Store build configuration, P50 decreased from over 16 minutes to less than 8 minutes.
- OpenAI: [codex: move the Windows Bazel jobs, often the long pole, to a faster runner group](https://github.com/openai/codex/pull/24952)
