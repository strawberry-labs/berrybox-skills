# Put stall limits and bounded retries on every network fetch

Make checkout, submodules, downloads and package installs give up on a stalled transfer within about a minute and retry it two or three times with backoff, so a bad connection costs seconds instead of a failed or hung job.

- Playbook: [Make a red build mean something broke](https://berrybox.io/playbooks/flaky-tests.md)
- Saves: wait time and runner minutes
- Risk: low
- Web page: https://berrybox.io/playbooks/flaky-tests/resilient-network

## Signals in your baseline

- Failed first attempts end in checkout, submodule, install or download steps with resets, timeouts, 429 or 5xx errors.
- A setup step's p90 in the baseline sits far above its p50, or jobs hit timeout-minutes while still in checkout or install.
- curl or wget calls in workflows and scripts have no retry or timeout options.
- Checkout fetches submodules (submodules: true or recursive), and actions/checkout tries that fetch only once.

## Why it works

Network trouble reaches CI in two forms. A request fails outright, with a reset, a DNS error, a 429 or a 5xx, and trying again a few seconds later usually works. Or a transfer stalls: the connection stays open, data stops arriving, and nothing fails. Without a stall limit, the step waits until the job's `timeout-minutes` (360 by default), and only then can anything retry. Nethermind watched a stalled submodule clone sit until its 20-minute job timeout, because its retry loop only ran after a failure. After Linear's runner provider traced checkout hangs to a degraded network link, Linear moved to its own checkout action with backoff retries and a stall limit of about 30 seconds.

So give every fetch three things: a stall limit that turns a hang into an error, two or three retries with growing waits, and a step timeout as the last stop. Fewer runs fail before a single test runs, and a bad connection costs seconds.

## Apply it

### Git checkout and submodules

`actions/checkout` retries its fetch of your repository up to three times, but runs `git submodule update` once. Git aborts a transfer that stays below `GIT_HTTP_LOW_SPEED_LIMIT` bytes per second for `GIT_HTTP_LOW_SPEED_TIME` seconds, and checkout passes the job's environment to git, so setting both at the workflow level covers checkout and every later git command:

```yaml
env:
  GIT_HTTP_LOW_SPEED_LIMIT: "1000"
  GIT_HTTP_LOW_SPEED_TIME: "60"

jobs:
  build:
    runs-on: ubuntu-24.04
    timeout-minutes: 30
    steps:
      - uses: actions/checkout@v7
        timeout-minutes: 10
        with:
          submodules: false
      - name: Fetch submodules, up to 3 attempts
        timeout-minutes: 15
        shell: bash
        run: |
          for attempt in 1 2 3; do
            git submodule sync --recursive
            if git submodule update --init --force --recursive --depth 1; then
              exit 0
            fi
            echo "::warning title=Retried network step::submodule fetch failed on attempt $attempt"
            sleep $((attempt * 15))
          done
          exit 1
```

- 1,000 bytes per second for 60 seconds is what Nethermind and Slang use. A slow transfer that still moves data continues; a dead one fails within a minute and the loop tries again.
- `submodules: false` plus the loop replaces checkout's single submodule attempt with three. Slang made the same split after counting 19 jobs lost to submodule fetches in four days.
- This works as written for public submodules. Checkout sets up credentials for private submodules only around its own fetch, so a later step needs its own token.
- The step timeouts stop any hang the low-speed limit doesn't catch.

### Downloads

```bash
curl --fail --location --silent --show-error \
  --connect-timeout 10 --speed-limit 1000 --speed-time 60 \
  --retry 3 --retry-connrefused \
  --output tool.tar.gz "$TOOL_URL"
```

`--retry` covers timeouts, including a `--speed-limit` abort, and HTTP 408, 429, 500, 502, 503 and 504 responses, waiting 1 second and doubling. `--retry-connrefused` adds refused connections. `--retry-all-errors` also retries resets and 404s, but curl's manual advises against using it by default. Keep the checksum check from [pinned tools](https://berrybox.io/playbooks/flaky-tests/pin-service-images.md) after the download.

### Package managers

Most installers already retry, so don't wrap them in another loop. Tune the stall time instead:

- npm retries a failed fetch twice but waits up to 5 minutes for a request (`fetch-timeout`). Lower it with `npm_config_fetch_timeout: "60000"` if installs stall.
- pip makes up to 5 attempts to open a connection, with a 15-second socket timeout. uv retries 3 times with a 30-second read timeout (`UV_HTTP_RETRIES`, `UV_HTTP_TIMEOUT`).
- apt: `sudo apt-get -o Acquire::Retries=3 install -y ...`.

A source that rate-limits you needs replacing, not more retries. Stripe moved Java installs from SDKMAN, whose rate limits were failing builds, to direct downloads from Adoptium with a cache. Caching removes most fetches entirely: see [cache dependencies](https://berrybox.io/playbooks/slow-setup/cache-dependencies.md) and [cache tool downloads](https://berrybox.io/playbooks/slow-setup/cache-tool-downloads.md).

## Keep it safe

- **Retry reads only.** These loops are for fetches. Never wrap a deploy, a publish or a migration in one ([retry narrowly](https://berrybox.io/playbooks/flaky-tests/retry-narrowly.md)).
- **Budget the time.** Attempts times the per-attempt limit, plus the waits, must fit inside the step's `timeout-minutes`, and that inside the job's.
- **No security shortcuts.** Never add `--insecure`, `GIT_SSL_NO_VERIFY` or `--trusted-host` to get past a failing connection, and keep checksums on every retried download. A fallback mirror must serve the same verified files.
- **Shared mirrors and caches.** A persistent git mirror or download cache, like the one Linear uses, should only be written by trusted runs on the default branch. If fork pull requests can write to it, they can poison every later run.
- **Thresholds.** A stall limit set too high kills slow but healthy transfers. Keep the floor low and the window around a minute.
- **Required checks.** Splitting checkout into two steps doesn't rename the job. Moving it into a reusable workflow does add the caller's job name as a prefix, so update branch protection if you do that.
- **Logs.** Don't `set -x` in loops that use tokens, and keep credentials out of URLs that a failed attempt would print.

## Verify

- Rerun the first-attempt query from the [flaky tests](https://berrybox.io/playbooks/flaky-tests.md) page. Failures in checkout, submodule, install and download steps should drop to near zero.
- In the [baseline](https://berrybox.io/playbooks/baseline.md) steps table, the p90 of checkout and install steps should fall if stalls were inflating it.
- Count the `Retried network step` warnings each week. A step that keeps retrying needs a better source, such as a cache or mirror, not more attempts.
- The same tests should run, and every required check should report under its old name.

## Sources

- Linear: [Linear blog: swap actions/checkout for its own composite action with backoff retries and git low-speed limits](https://linear.app/now/ci-bottleneck-reworked#make-checkout-more-resilient)
- Slang: [slang: fetch submodules in a separate step with retries, growing waits, git low-speed limits and a step timeout](https://github.com/shader-slang/slang/pull/13873). The linked issue counted 19 jobs that failed while fetching submodules between October 13 and 16, 2026, 16 of them on self-hosted Windows runners.
- Nethermind: [nethermind: abort stalled submodule clones with git's low-speed limits so the existing retry loop can run](https://github.com/NethermindEth/nethermind/pull/15015)
- Stripe: [stripe-android: download Java directly from Adoptium and cache it instead of installing through rate-limited SDKMAN](https://github.com/stripe/stripe-android/pull/12402)
