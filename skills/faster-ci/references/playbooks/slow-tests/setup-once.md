# Build shared fixtures and test databases once

Run migrations, seed data, logins and compilation once per run or once per image, then give each worker a cheap copy, instead of repeating the same setup in every worker, test file or container.

- Playbook: [Make the test suite finish sooner](https://berrybox.io/playbooks/slow-tests.md)
- Saves: wait time and runner minutes
- Risk: medium
- Web page: https://berrybox.io/playbooks/slow-tests/setup-once

## Signals in your baseline

- pytest --durations, or per-file times in Vitest or Jest, show the same setup (migrations, seeding, login) costing seconds in every worker or file.
- Test setup replays the full migration history on every run, though the schema rarely changes.
- Tests start subprocesses that each load a TypeScript compiler or re-import a large module graph from scratch.
- Test containers initialize their database at every start.

## Why it works

Much of a suite's setup produces the same result every time: the schema, seed data, a logged-in session, compiled sources. Doing it once per worker, per file or per container multiplies its cost by that count, and parallel copies compete for the same database and CPU. Ramp found that concurrent schema setup from every worker exhausted Postgres memory and capped how many workers they could run.

Do the work once and hand out copies. Postgres copies a migrated database with `CREATE DATABASE ... TEMPLATE` much faster than it replays migrations. A schema dump loads in one pass. A saved browser session skips the login form in every test. Compiled JavaScript skips the compiler.

## Apply it

### A template database for pytest-xdist workers

The first worker to take the lock builds a migrated template, and every worker clones it:

```python
# conftest.py
import os
import psycopg
import pytest
from filelock import FileLock  # pip install filelock

ADMIN_URL = os.environ["DATABASE_URL"]  # e.g. postgresql://postgres:postgres@127.0.0.1:5432/postgres
SERVER = ADMIN_URL.rsplit("/", 1)[0]
TEMPLATE = "app_test_template"

def admin(sql):
    with psycopg.connect(ADMIN_URL, autocommit=True) as conn:
        conn.execute(sql)

def build_template():
    admin(f'DROP DATABASE IF EXISTS "{TEMPLATE}" WITH (FORCE)')
    admin(f'CREATE DATABASE "{TEMPLATE}"')
    run_migrations(f"{SERVER}/{TEMPLATE}")  # your migration command; it must close its connections

@pytest.fixture(scope="session")
def database_url(tmp_path_factory, worker_id):
    if worker_id == "master":  # no xdist: a single process
        build_template()
    else:
        run_dir = tmp_path_factory.getbasetemp().parent  # shared by this run's workers only
        with FileLock(str(run_dir / "template.lock")):
            if not (run_dir / "template.ready").exists():
                build_template()
                (run_dir / "template.ready").touch()
    name = f"app_test_{worker_id}"
    admin(f'DROP DATABASE IF EXISTS "{name}"')
    admin(f'CREATE DATABASE "{name}" TEMPLATE "{TEMPLATE}"')
    yield f"{SERVER}/{name}"
    admin(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
```

- `CREATE DATABASE ... TEMPLATE` fails while any session is connected to the template, so the migration step must disconnect when it finishes.
- Without xdist, the base temp directory's parent is shared by every run on the machine, so the `master` branch skips the marker file to avoid reusing an old template.
- pytest-django users can get most of this from `--reuse-db` locally and `--nomigrations` in CI, which builds tables straight from the models.

### Load a schema snapshot instead of replaying migrations

Commit a schema dump (`pg_dump --schema-only --no-owner`, Rails `structure.sql`) and load it in tests. Add a CI step that rebuilds the dump from the migrations and fails on any difference, and keep one job that runs the real migrations, so a broken migration still fails CI.

### Vitest, Jest and Playwright

- Use `globalSetup` for work every worker shares: start containers, build the template, compile fixtures. It runs once before the workers start. Pass results through environment variables or Vitest's `project.provide()` and `inject()`.
- In Playwright, log in once in a setup project, save the session with `page.context().storageState({ path: 'playwright/.auth/user.json' })`, and give the other projects `dependencies: ['setup']` and `use: { storageState: 'playwright/.auth/user.json' }`.
- If tests spawn processes that each compile TypeScript, compile once in `globalSetup` or a build step and run the output. Setting `NODE_COMPILE_CACHE` to a directory lets Node 22 and later reuse compiled code across processes.
- For Python subprocesses, run `python -m compileall` on the code once before the tests.

### Images

When every container initializes the same database, do it when you build the image instead, as Materialize did. See [Prebake images](https://berrybox.io/playbooks/slow-setup/prebake-images.md).

## Keep it safe

- Keep shared state read-only. Every worker writes to its own copy, never to the template or a shared seed.
- Snapshots go stale. Key any cached template or dump on a hash of the migrations, and keep the dump check and the real-migration job.
- The `storageState` file holds session cookies and tokens. Add `playwright/.auth` to `.gitignore`, keep it out of uploaded artifacts and use a test account.
- One-time setup is a single point of failure. Make it fail loudly with its own error, not with every test timing out.

## Verify

- Setup time per worker or file should drop to roughly the cost of a copy. Check `pytest --durations=20` (setup phases are listed separately) or the per-file times in Vitest or Jest.
- Compare the test step's p50 with the [baseline](https://berrybox.io/playbooks/baseline.md).
- Confirm the same number of tests passed, and that a deliberate change to a migration makes the dump check fail.

## Sources

- Ramp: [Ramp Builders: let one pytest-xdist worker apply the database schema instead of every worker](https://builders.ramp.com/post/faster-python-tests). Coordinating which worker applies the schema let them run more workers, double the machine size and halve CI test times.
- Linear: [Linear Now: load a generated schema snapshot instead of replaying every migration](https://linear.app/now/ci-bottleneck-reworked#avoid-replaying-unchanged-setup). Database setup dropped from roughly 12 seconds to 1-2 seconds per container.
- Materialize: [Materialize blog: initialize PostgreSQL ahead of time instead of at container start](https://materialize.com/blog/speeding-up-materialize-ci/). Container startup went from 40 s to 5.6 s.
- OpenAI: [openai-node: compile test sources once per Vitest run instead of in every subprocess](https://github.com/openai/openai-node/pull/2713). With sources compiled once per run, Node's compile cache and smaller overhead cuts, the Node 22 test step went from 3m44s to 1m58s in one measured run.
