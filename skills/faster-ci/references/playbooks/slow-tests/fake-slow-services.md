# Keep unit tests off real networks and services

Give unit tests in-process fakes for databases, caches, HTTP APIs and subprocesses, block outbound connections so a missing mock fails at once instead of after a timeout, and run real-service tests in a separate integration job.

- Playbook: [Make the test suite finish sooner](https://berrybox.io/playbooks/slow-tests.md)
- Saves: wait time and runner minutes
- Risk: medium
- Web page: https://berrybox.io/playbooks/slow-tests/fake-slow-services

## Signals in your baseline

- The unit test job starts service containers (Postgres, Redis, Kafka) that most of its tests never use, and its Initialize containers step takes a noticeable share of the job.
- The slowest tests in pytest --durations or the Jest and Vitest reports take whole seconds, often a multiple of a client timeout, because they wait on network calls.
- Unit tests call third-party APIs, resolve real hostnames or start a subprocess for every case.

## Why it works

A unit test that talks to a real service pays three times. The job waits for the service container to start. Every call adds a network round trip. And when a call goes somewhere it shouldn't, such as an unmocked API or a host that doesn't answer, the test sits through the client's full timeout, sometimes with retries, before it fails or falls back. A few of those can dominate a suite, as one missing mock did in OpenAI's resolver tests.

In-process fakes answer in microseconds and need no container: fakeredis instead of Redis, an `httptest` server or MSW handlers instead of a remote API, an in-memory repository instead of a database. The same applies to processes: launching an interpreter per case costs tens to hundreds of milliseconds that a direct function call doesn't. Fakes can drift from the real thing, so a smaller integration job still runs against real services. The unit job then starts nothing and finishes sooner.

## Apply it

Block the network in the unit job first. Every test that fails then names a dependency to fake:

- pytest: install pytest-socket and run with `--disable-socket --allow-unix-socket` (or `--allow-hosts=127.0.0.1` when tests use local fakes that listen on TCP). Mark the tests that need real services with `@pytest.mark.integration`.
- Vitest or Jest: start an MSW server in a setup file with `server.listen({ onUnhandledRequest: 'error' })`, or call `nock.disableNetConnect()`.
- Go: skip service-backed tests with `if testing.Short() { t.Skip("needs Postgres") }`, run `go test -short ./...` in the unit job, and serve fake APIs with `httptest.NewServer`.

Then split the job:

```yaml
jobs:
  unit:
    runs-on: ubuntu-latest
    timeout-minutes: 15
    steps:
      - uses: actions/checkout@v7
      - uses: actions/setup-python@v7
        with:
          python-version: "3.13"
          cache: pip
      - run: pip install -r requirements-dev.txt pytest-socket pytest-xdist
      - run: pytest -m "not integration" -n auto --disable-socket --allow-unix-socket

  integration:
    runs-on: ubuntu-latest
    timeout-minutes: 20
    services:
      postgres:
        image: postgres:17
        env:
          POSTGRES_PASSWORD: postgres
        ports:
          - 5432:5432
        options: >-
          --health-cmd "pg_isready -h 127.0.0.1 -U postgres"
          --health-interval 2s
          --health-timeout 5s
          --health-retries 30
    env:
      DATABASE_URL: postgresql://postgres:postgres@127.0.0.1:5432/postgres
    steps:
      - uses: actions/checkout@v7
      - uses: actions/setup-python@v7
        with:
          python-version: "3.13"
          cache: pip
      - run: pip install -r requirements-dev.txt
      - run: pytest -m integration
```

- `-m "not integration"` and `-m integration` together select every test exactly once. Register the marker in the pytest config and add `--strict-markers` so a typo can't drop tests from both jobs.
- The unit job has no `services` block, so its Initialize containers step disappears, and it needs no secrets.
- Use `127.0.0.1` rather than `localhost` for local servers. `localhost` may resolve to IPv6 first and fall back, and some systems resolve it slowly.

For the fakes themselves: fakeredis, respx or responses in Python; MSW in Node; `httptest` in Go. Fake the database at your repository interface. SQLite is a fair stand-in only for queries that don't use Postgres- or MySQL-specific SQL, which is how Cadence used it. Where a test runs a CLI or script per case, call its entry function in-process and keep a few true subprocess tests for the command-line surface.

## Keep it safe

- Fakes drift. Keep at least one integration test per real adapter and query path, run it on every pull request or in the merge queue, and move service-backed tests instead of deleting them, as Cadence did.
- Splitting a job changes check names. Require both new jobs, or keep the old name on an aggregate job as in [Shard tests](https://berrybox.io/playbooks/slow-tests/shard-tests.md), so branch protection still waits for both.
- Recorded responses (VCR cassettes, HAR files) can hold API keys and personal data. Filter authorization headers and tokens before committing them.
- An `xfail` or skip added only because the network is blocked hides a test. Move the test to the integration job instead.

## Verify

- Compare the unit job's p50 with the [baseline](https://berrybox.io/playbooks/baseline.md). Initialize containers should be gone from it, and `pytest --durations=20` should no longer list multi-second network waits.
- The unit and integration test counts should add up to the old total of passed plus skipped tests.
- The unit job should pass with network access blocked.

## Sources

- OpenAI: [OpenAI developer blog: add the mock a resolver test suite was missing](https://developers.openai.com/blog/maintaining-software-with-the-gpt-6-family#other-ideas-to-try). Adding a missing mock cut a 63-test resolver suite from 592.6 seconds to 29.8 seconds, with all 63 tests kept.
- Sentry: [Sentry blog: drop an unused Redis service and start Postgres only for the tests that need it](https://blog.sentry.io/how-we-run-our-python-tests-in-hundreds-of-environments-really-fast/). Removing Redis (the tests already used fakeredis) and starting Postgres only for the Django tests saved about 5 more minutes.
- Cadence: [cadence: remove service dependencies from the unit test container and move persistence tests to integration](https://github.com/cadence-workflow/cadence/pull/6800)
- OpenAI: [openai-python: run 1,760 policy test cases in-process instead of one subprocess each](https://github.com/openai/openai-python/pull/3830). The Python 3.14 test job went from 7m00s to 2m41s; the team measured a median of 180ms per subprocess case against 0.9ms in-process.
