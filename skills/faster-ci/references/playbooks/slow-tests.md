# Make the test suite finish sooner

Run tests on every core without shared state, replace sleeps, real services and repeated setup with cheaper equivalents, then split what remains across shards balanced by recorded timings.

Web page: https://berrybox.io/playbooks/slow-tests

## Signals in your baseline

- A test job is the long pole on the critical path, and its test step takes most of that job's time.
- The test command runs serially (--runInBand, workers 1, pytest without -n) on a runner with two or more vCPUs.
- The shards of a sharded test job finish far apart, and the same shard is the slowest in most runs.
- Tests sleep for fixed times, start services most of them never use, or repeat migrations and logins in every worker.

When a test job is the long pole, most of its time is usually the test step itself, not setup. These plays shorten that step, first on one machine and then across several. They change how tests run, not which tests run. To run fewer tests per change, see [Test selection](https://berrybox.io/playbooks/test-selection.md).

## Confirm it in your baseline

- In **Critical paths**, check that a test job is the long pole in most runs.
- In **Steps inside the long-pole jobs**, the test step should hold most of the job's time. If checkout, install or build hold most of it, start with [Slow setup](https://berrybox.io/playbooks/slow-setup.md).
- In the workflow and test config, look for serial settings: `--runInBand`, `--maxWorkers=1`, `workers: 1`, `fileParallelism: false`, pytest without `-n`, or a shell loop over Go packages.
- For a job that is already sharded, compare the shards' p50 in **Slowest jobs**. A wide spread means unbalanced shards.
- Run the suite once with `pytest --durations=25` or your runner's slow-test report, and grep the tests for fixed sleeps. Tests that take whole seconds are usually waiting on a sleep, a timeout or setup.

## Order of work

Start on one machine, where gains are cheapest. Fix shared state first with [Isolate test state](https://berrybox.io/playbooks/slow-tests/isolate-test-state.md), because every later step adds parallelism that exposes it, then [match workers to cores](https://berrybox.io/playbooks/slow-tests/match-workers-to-cores.md). [Polling instead of sleeping](https://berrybox.io/playbooks/slow-tests/poll-dont-sleep.md), [fake services](https://berrybox.io/playbooks/slow-tests/fake-slow-services.md) and [one-time setup](https://berrybox.io/playbooks/slow-tests/setup-once.md) remove work outright, so they save runner minutes as well as wall time. Shard last: every shard repeats setup, so [sharding](https://berrybox.io/playbooks/slow-tests/shard-tests.md) trades minutes for wall time, and [balancing](https://berrybox.io/playbooks/slow-tests/balance-shards.md) only matters once shards exist.

## Plays

- [Split a long test suite across parallel jobs](https://berrybox.io/playbooks/slow-tests/shard-tests.md): Run the suite as a matrix of shards with the test runner's own shard flag, gate merges on one aggregate job, merge the shard reports and confirm that every test ran exactly once. Saves wait time; medium risk.
- [Balance shards by recorded test timings](https://berrybox.io/playbooks/slow-tests/balance-shards.md): Assign tests to shards by how long they took on the default branch instead of by count, give every shard the same timings file and refresh it after each merge so no shard trails the others. Saves wait time; medium risk.
- [Match test workers to the runner's cores and memory](https://berrybox.io/playbooks/slow-tests/match-workers-to-cores.md): Set the test runner's worker count from the CPUs and memory the CI runner actually has, instead of running serially or copying a laptop setting, and cap it where memory or a shared service runs out first. Saves wait time and runner minutes; medium risk.
- [Isolate test state so tests can run in parallel](https://berrybox.io/playbooks/slow-tests/isolate-test-state.md): Give each test worker its own database, ports, files and environment, find order dependencies by shuffling, and run the few tests that must share a resource in a serial lane, so more workers stop meaning more flakes. Saves wait time and runner minutes; medium risk.
- [Wait for readiness, not for a fixed sleep](https://berrybox.io/playbooks/slow-tests/poll-dont-sleep.md): Replace fixed sleeps in tests and workflows with polls for the condition you need, such as a health check, a page marker or a signal from the code, so each wait ends as soon as it can and never too early. Saves wait time and runner minutes; low risk.
- [Build shared fixtures and test databases once](https://berrybox.io/playbooks/slow-tests/setup-once.md): Run migrations, seed data, logins and compilation once per run or once per image, then give each worker a cheap copy, instead of repeating the same setup in every worker, test file or container. Saves wait time and runner minutes; medium risk.
- [Keep unit tests off real networks and services](https://berrybox.io/playbooks/slow-tests/fake-slow-services.md): Give unit tests in-process fakes for databases, caches, HTTP APIs and subprocesses, block outbound connections so a missing mock fails at once instead of after a timeout, and run real-service tests in a separate integration job. Saves wait time and runner minutes; medium risk.
