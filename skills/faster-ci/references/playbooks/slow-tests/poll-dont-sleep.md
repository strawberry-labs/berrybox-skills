# Wait for readiness, not for a fixed sleep

Replace fixed sleeps in tests and workflows with polls for the condition you need, such as a health check, a page marker or a signal from the code, so each wait ends as soon as it can and never too early.

- Playbook: [Make the test suite finish sooner](https://berrybox.io/playbooks/slow-tests.md)
- Saves: wait time and runner minutes
- Risk: low
- Web page: https://berrybox.io/playbooks/slow-tests/poll-dont-sleep

## Signals in your baseline

- Test code waits for fixed times, such as time.sleep(, time.Sleep(, page.waitForTimeout( or an awaited setTimeout.
- Workflow steps or scripts run sleep N before tests, or start services with docker compose up -d and no --wait.
- Service containers have no health check, or one that only checks that a port accepts connections.

## Why it works

A fixed sleep is a guess about how long something takes. When the guess is long, every run pays all of it, even when the service was ready in a tenth of the time, and a 2-second wait on each of about 50 routes adds about 100 seconds. When the guess is short, a slow or busy runner misses it and the test fails for no reason. Polling for the real condition ends the wait the moment it holds and keeps waiting, up to a generous deadline, when the machine is slow. Runs get faster and less flaky at the same time.

The condition has to be the one the next step needs. An open port isn't a database that accepts queries. MySQL and Postgres containers can answer on their Unix socket while clients connecting over TCP are still refused, which is the flake Uber fixed by health-checking over `127.0.0.1`.

## Apply it

Find the fixed waits:

```bash
git grep -nE 'time\.sleep\(|time\.Sleep\(|waitForTimeout\(|setTimeout\(resolve|(^|[ ;])sleep [0-9]' \
  -- '*test*' '*spec*' '*.sh' '.github/workflows' 'docker-compose*' 'compose*'
```

### In tests

- Vitest: `await vi.waitFor(() => expect(queue.size).toBe(0), { timeout: 10_000, interval: 50 })`.
- Playwright: delete `page.waitForTimeout`. Web-first assertions such as `await expect(page.getByText('Saved')).toBeVisible()` already retry until their timeout, and `await expect.poll(() => fetchStatus(id), { timeout: 30_000 }).toBe('done')` covers values outside the page.
- Go: `require.Eventually(t, srv.Ready, 10*time.Second, 20*time.Millisecond)`. Better still, wait on a channel or callback the code fires when the work is done, as Uber did for its queue's poll loop.
- Python: use a small helper and call it with the condition:

```python
import time

def wait_until(check, timeout=10.0, interval=0.05):
    deadline = time.monotonic() + timeout
    while not check():
        if time.monotonic() > deadline:
            raise TimeoutError(f"condition not met within {timeout}s")
        time.sleep(interval)
```

- Code that waits on purpose (retries, debounce, expiry) should run under fake timers (`vi.useFakeTimers()`, `jest.useFakeTimers()`, time-machine or freezegun, an injected clock in Go), not real sleeps.

### In workflows

```yaml
jobs:
  test:
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
    steps:
      - uses: actions/checkout@v7
      - run: docker compose up -d --wait --wait-timeout 120
      - name: Start the app and wait for its health endpoint
        run: |
          npm run start:test &
          timeout 60 bash -c 'until curl -fsS http://127.0.0.1:3000/health > /dev/null; do sleep 0.5; done'
      - run: npm test
```

- The runner waits for a service container's health check to pass before it starts the steps, so no `sleep` is needed after it.
- `pg_isready -h 127.0.0.1` checks over TCP. During first-boot initialization the Postgres image runs a temporary server on the Unix socket only, so a socket check can pass too early.
- `docker compose up --wait` returns when every service is running and every health check passes. A service without a `healthcheck` counts as ready as soon as it starts, so give each one a check that makes a real request (`mysqladmin ping -h 127.0.0.1`, `redis-cli ping`), not a port check.
- The `until` loop polls every half second and `timeout 60` fails the step instead of hanging until the job timeout. A background process keeps running into later steps of the same job.

## Keep it safe

- Every poll needs a deadline, and the deadline should be longer than the sleep it replaces. A fast pass costs nothing extra; a slow runner gets more room.
- Poll what the test depends on. A web server can answer before migrations finish, so point the health endpoint at the dependencies it needs.
- A check that something does *not* happen can't end early. Keep a short, bounded wait for those, or assert on an explicit signal, such as a processed-message count.
- Don't shorten sleeps that exercise timing behavior, such as timeouts and rate limits. Use fake timers or shorter configured durations instead.
- Poll shared services every 50 to 500 ms, not in a tight loop.

## Verify

- The grep above should return fewer hits.
- Compare the test step and any service-start step with their p50 in the [baseline](https://berrybox.io/playbooks/baseline.md).
- Run the suite three to five times. No new failures should appear, and the same number of tests should pass. Watch the rerun rate for a week.

## Sources

- CNCF: [CNCF end-user site: wait for Docusaurus's hydration marker instead of 2 seconds on every route](https://github.com/cncf/endusers/pull/1907). Locally, the spec's 50 tests passed in 8.5s, against about 112s cumulative before.
- Cadence: [cadence: replace a 50 ms time.Sleep with require.Eventually in a test that failed on slow runners](https://github.com/cadence-workflow/cadence/pull/7904)
- Uber: [submitqueue: check MySQL health over TCP so compose reports ready only when clients can connect](https://github.com/uber/submitqueue/pull/64)
- Uber: [submitqueue: wait for the poll loop's signal before asserting consumer lag](https://github.com/uber/submitqueue/pull/274)
