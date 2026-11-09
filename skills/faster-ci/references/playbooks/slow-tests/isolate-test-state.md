# Isolate test state so tests can run in parallel

Give each test worker its own database, ports, files and environment, find order dependencies by shuffling, and run the few tests that must share a resource in a serial lane, so more workers stop meaning more flakes.

- Playbook: [Make the test suite finish sooner](https://berrybox.io/playbooks/slow-tests.md)
- Saves: wait time and runner minutes
- Risk: medium
- Web page: https://berrybox.io/playbooks/slow-tests/isolate-test-state

## Signals in your baseline

- Tests pass when run one at a time but fail or flake with more workers, --shard, -n or fullyParallel.
- Parallelism is switched off on purpose: --runInBand, workers: 1, fileParallelism: false, or a comment saying the tests can't run in parallel.
- Test code or config hard-codes a port, a single database name, a fixed path under /tmp or one shared external account.

## Why it works

Parallel workers run tests at the same time in separate processes. Anything outside a process (a database, a port, a file, a test account) is shared by all workers, and anything inside one (environment variables, the working directory, module-level singletons) carries over to the next test that worker runs. Two tests that write the same row or bind the same port fail only when they happen to overlap, so the failures look random, and teams turn parallelism off instead of fixing them.

Give every worker its own copy of each outside resource, named after a worker ID the runner provides, and reset in-process state after each test. Then the worker count becomes a tuning knob ([Match workers to cores](https://berrybox.io/playbooks/slow-tests/match-workers-to-cores.md)) instead of a risk.

## Apply it

### Find what collides

Run the suite shuffled and with several workers, a few times, and keep the failing seeds:

```bash
pip install pytest-randomly && pytest -n 4    # shuffled by default; replay with --randomly-seed=N
seed=$RANDOM; echo "seed=$seed"; npx vitest run --sequence.shuffle --sequence.seed=$seed
npx jest --randomize --showSeed               # replay with --seed=N
go test -shuffle=on -count=1 -race ./...      # replay with -shuffle=N
```

A test that fails only after another test ran depends on leftover state. Fix that test; don't pin the order.

### Give each worker its own resources

Start with the database: one per worker. pytest-django already suffixes test databases per xdist worker (`test_app_gw0`). Without it:

```python
# conftest.py
import os
import psycopg
import pytest

@pytest.fixture(scope="session")
def database_url(worker_id):  # "gw0", "gw1", ... under xdist, "master" without it
    admin_url = os.environ["DATABASE_URL"]  # e.g. postgresql://postgres:postgres@127.0.0.1:5432/postgres
    name = f"app_test_{worker_id}"
    with psycopg.connect(admin_url, autocommit=True) as conn:
        conn.execute(f'DROP DATABASE IF EXISTS "{name}"')
        conn.execute(f'CREATE DATABASE "{name}"')
    yield admin_url.rsplit("/", 1)[0] + "/" + name
    with psycopg.connect(admin_url, autocommit=True) as conn:
        conn.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
```

Run migrations against the new database, or clone a migrated template ([Set up once](https://berrybox.io/playbooks/slow-tests/setup-once.md)). In a Vitest or Jest setup file, build the name from `process.env.VITEST_POOL_ID ?? process.env.JEST_WORKER_ID`; in Playwright, from `testInfo.parallelIndex` in a worker-scoped fixture. Inside a worker, wrapping each test in a transaction that rolls back is cheaper still, if the code under test doesn't commit or open its own connections.

Then the rest:

- **Ports:** listen on port 0 and read the assigned port back (`server.listen(0)`, `httptest.NewServer`, `socket.bind(("127.0.0.1", 0))`).
- **Files:** use the runner's temporary directories (`tmp_path`, `t.TempDir()`, `fs.mkdtemp`), never a fixed path.
- **Environment and globals:** change them through helpers that restore them (`monkeypatch`, `vi.stubEnv` with `unstubEnvs: true`). Go's `t.Setenv` refuses to run in parallel tests. Reset registries and singletons in an autouse fixture or `afterEach`.
- **External accounts:** give each worker its own test account, store or bucket, and put the worker ID and `GITHUB_RUN_ID` in its name so parallel CI runs don't collide either.

### Put what must share in a serial lane

- pytest-xdist: mark the tests with `@pytest.mark.xdist_group("billing-sandbox")` and run with `--dist loadgroup`. Each group runs on one worker while the rest stay parallel.
- Playwright: move them into a project with `workers: 1` (Playwright 1.52 and later), or use `test.describe.configure({ mode: 'serial' })` for dependent tests in one file.
- Go: leave out `t.Parallel()` for those tests. Packages still run in parallel, so a resource shared across packages needs a per-package name.

### Share setup again, on purpose

Once tests pass shuffled, you can drop isolation the runner pays for on every file. Vitest's `isolate: false` reuses one module graph per worker. Linear put it in a separate project that files join only by opting in, after their state is cleaned up.

## Keep it safe

- Don't hide collisions behind retries or a lower worker count. They are real bugs that also break local parallel runs.
- Per-worker databases multiply connections. Check `max_connections` against workers × pool size.
- Serial lanes must still run. Confirm the test count matches a serial run after adding `xdist_group` or a new project.
- Drop per-worker databases and containers at the end. A disposable runner throws them away, but a persistent self-hosted runner keeps them.
- `isolate: false` lets one file's leftovers reach the next. Opt in only files that pass shuffled runs, and keep the rest isolated.

## Verify

- Run the suite three to five times at the target worker count with shuffling on. No new failures should appear.
- Compare the test step's p50 with the [baseline](https://berrybox.io/playbooks/baseline.md) at the higher worker count.
- Confirm the same number of tests passed and skipped, including the serial lanes.

## Sources

- Shopify: [Shopify CLI: run E2E tests on five Playwright workers after giving each worker its own dev store and ports](https://github.com/Shopify/cli/pull/7309). The E2E suite completed in about 10 minutes with 5 workers, down from about 27 minutes with 1 worker.
- DoorDash: [agentic-orchestrator: run packaged E2E journeys on three workers, each in a throwaway home, workspace and port](https://github.com/doordash-oss/agentic-orchestrator/pull/139)
- Stripe: [sync-engine-fork: run E2E test files in parallel, each against its own Postgres container](https://github.com/stripe/sync-engine-fork/pull/124)
- Linear: [Linear Now: let files that pass strict rules share module state in an opt-in Vitest project](https://linear.app/now/ci-bottleneck-reworked#share-module-state-only-with-strict-isolation-rules). The slowest shard fell from roughly 300-379 seconds to about 195 seconds, and API-shard runner time from about 32.8 to 22 minutes per run.
