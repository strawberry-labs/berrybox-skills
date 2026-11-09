# Match test workers to the runner's cores and memory

Set the test runner's worker count from the CPUs and memory the CI runner actually has, instead of running serially or copying a laptop setting, and cap it where memory or a shared service runs out first.

- Playbook: [Make the test suite finish sooner](https://berrybox.io/playbooks/slow-tests.md)
- Saves: wait time and runner minutes
- Risk: medium
- Web page: https://berrybox.io/playbooks/slow-tests/match-workers-to-cores

## Signals in your baseline

- The test command runs serially: --runInBand or --maxWorkers=1 in Jest, workers: process.env.CI ? 1 : undefined in Playwright, pytest without -n, or a shell loop that runs go test once per package.
- A hard-coded worker count doesn't match the vCPUs of the runner label shown in the Slowest jobs table.
- Test jobs sometimes die with exit code 137, "Killed", "JavaScript heap out of memory" or a runner that lost communication with the server.

## Why it works

A test runner with one worker uses one core, and a CI runner usually has two or four. Most test runners can use several workers, but their CI defaults often leave cores idle. Jest uses cores minus one, which is a single worker on a 2-vCPU runner. Playwright projects scaffolded before 2026 set one worker on CI. pytest runs serially until pytest-xdist is installed and `-n` is passed. A shell loop over Go packages throws away `go test`'s own package parallelism.

More workers help until something runs out. Past the core count, workers just take turns. Each worker holds its own copy of the code under test, and when the total passes the runner's RAM the kernel kills a process (exit 137) or the runner stops reporting. And one database or rate-limited API serves only so many workers at once. Pick the fastest count that stays under all three limits.

## Apply it

First check what the runner really has. GitHub's standard Linux runners have 2 vCPUs and 8 GB for private repositories and 4 vCPUs and 16 GB for public ones; self-hosted and container runners vary. Then measure one worker's memory: run the suite with a known worker count while sampling used memory, and divide the rise above the idle level by the worker count.

```yaml
      - name: Show runner capacity
        run: |
          echo "CPUs: $(nproc)"
          cat /sys/fs/cgroup/cpu.max 2>/dev/null || true
          free -m
      - name: Pick a worker count
        run: |
          cpus=$(nproc)
          avail_mib=$(awk '/MemAvailable/ {print int($2 / 1024)}' /proc/meminfo)
          per_worker_mib=1500   # measured peak for one worker; keep it current
          workers=$(( avail_mib / per_worker_mib ))
          workers=$(( workers > cpus ? cpus : workers ))
          workers=$(( workers < 1 ? 1 : workers ))
          echo "TEST_WORKERS=$workers" >> "$GITHUB_ENV"
      - name: Run tests
        run: npx vitest run --maxWorkers=$TEST_WORKERS
```

- `cpu.max` shows a CPU quota (`200000 100000` means two CPUs); `max` means none. Tools that count CPUs may ignore the quota on container and Kubernetes runners, so cap the count yourself there.
- `MemAvailable` already leaves out what the job's service containers hold. They can grow during the run, which the headroom below covers.
- To sample memory during a run, start `(while sleep 5; do free -m | awk '/^Mem:/ {print $3}'; done) > mem.log &` before the tests and print `sort -n mem.log | tail -1` after them.

### Node

- Jest: pass `--maxWorkers=$TEST_WORKERS` and remove `--runInBand` unless the tests share state. If memory creeps up over a long run, set `workerIdleMemoryLimit` (for example `"1GB"`) so Jest restarts bloated workers.
- Vitest: `maxWorkers` defaults to all available parallelism outside watch mode, and the default `forks` pool gives each worker its own process. The `threads` pool is often faster but breaks `process.chdir()` and some native modules. Vitest 5's `vitest doctor` times the suite under other pools and lower worker counts; run it once on the CI runner size.
- Playwright: replace `workers: process.env.CI ? 1 : undefined` with a number or a percentage such as `"50%"`. Each worker drives a browser, so memory often binds before CPU.

### Python

Install pytest-xdist and run `pytest -n auto`. With psutil installed, `auto` counts physical cores, which on many cloud VMs is half the vCPUs; `-n logical` counts vCPUs. Cap it with `--maxprocesses=$TEST_WORKERS`. `--dist loadfile` keeps each file on one worker, which suits module-level fixtures, and `--dist worksteal` lets idle workers take tests from busy ones when durations vary. With tox, `tox -p auto` runs environments in parallel.

### Go

Run all packages in one command, `go test ./...`. `-p` sets how many package test binaries run at once, and `-parallel` sets how many `t.Parallel()` tests run inside each binary; both default to `GOMAXPROCS`. Since Go 1.25, `GOMAXPROCS` respects a cgroup CPU limit on Linux. On older versions, set it yourself in containers with a limit.

## Keep it safe

- Parallel workers expose shared state: fixed ports, shared files, one database, global registries. If tests start failing only with more workers, fix them with [Isolate test state](https://berrybox.io/playbooks/slow-tests/isolate-test-state.md) instead of lowering the count and moving on.
- Leave about 20% of memory free. An out-of-memory kill often leaves no test output, only exit code 137 or a lost runner.
- Check connection limits on shared services. Postgres allows 100 connections by default, and each worker opens its own pool.
- Timeouts tuned on an idle machine can fire under contention. Check the worker count before raising them.
- Measure two or three counts. More workers can be slower: OpenAI found 12 slower than 8, and Vitest's single transform server limits how many workers help.

## Verify

- Compare the test step's p50 with the [baseline](https://berrybox.io/playbooks/baseline.md) for each worker count you tried. On the same runner, runner minutes fall with it.
- Confirm the same number of tests passed and skipped as before.
- Over the next week, look for exit code 137, "Killed" or lost runners, and check that the rerun rate didn't rise.

## Sources

- OpenAI: [codex: raise Bazel local test jobs on Windows shards from 4 to 8 after measuring 4, 8 and 12](https://github.com/openai/codex/pull/31352). Eight local jobs cut Bazel elapsed time on every shard by 19-29%, including the slow shard from 835.5s to 609.3s, while 12 jobs regressed.
- Sentry: [Sentry blog: run tox environments in parallel on each runner with --parallel auto](https://blog.sentry.io/how-we-run-our-python-tests-in-hundreds-of-environments-really-fast/). Running the environments in parallel took the suite from about 40 minutes to around 25, after which the runner's 2 CPU cores were the limit.
- Spotify: [luigi: run the core tests with pytest-xdist (-n auto --dist=loadfile) and reset the task registry around each test](https://github.com/spotify/luigi/pull/3398). The core test workflows now run in 2-4 minutes, 1-2 minutes faster.
- Cadence: [cadence: run Go unit test packages in one go test call instead of a loop over directories](https://github.com/cadence-workflow/cadence/pull/6801)
