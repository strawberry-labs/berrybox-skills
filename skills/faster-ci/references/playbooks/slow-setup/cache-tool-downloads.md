# Cache browsers, toolchains and CLI downloads

Keep downloaded browsers, compilers and CLIs between runs in a cache keyed on the exact tool version, or swap a compile-from-source step for a prebuilt binary, when the download is slow, flaky or rate-limited.

- Playbook: [Get setup off the clock](https://berrybox.io/playbooks/slow-setup.md)
- Saves: wait time and runner minutes
- Risk: low
- Web page: https://berrybox.io/playbooks/slow-setup/cache-tool-downloads

## Signals in your baseline

- Steps such as playwright install, rustup, cargo install, SDK managers or curl downloads take 30 seconds or more in the long-pole step table.
- Reruns trace back to failed tool downloads, such as TLS errors, HTTP 429 responses or CDN timeouts.
- A step compiles a tool from source (cargo install, go install, a protoc or linter build) on every run.
- The same pinned tool version is downloaded in many jobs of every run.

## Why it works

Package caches cover libraries, but many jobs also fetch tools: Playwright browsers, language toolchains, mobile SDKs, `protoc`, linters shipped as binaries, or a `cargo install` that compiles a CLI from source. Each one depends on an outside server, and some are not downloads at all but minutes of compiling. A pinned tool version always produces the same files, so you can cache them on a key built from that version and restore them in seconds. A slow or failing download then hits one warm-up run instead of every job.

Not every download is worth caching. Restoring from the GitHub cache takes time too, and Playwright's own CI guide advises against caching browsers because restoring them takes about as long as downloading them. Cache when the download is slow or unreliable from your runners, rate-limited, or really a compile. Otherwise, measure both before you add a cache.

## Apply it

### Tools you compile from source

Prefer a prebuilt binary when the project publishes one. Uber's switch from compiling `protoc` to a downloaded release is the cleanest version of this play. When you have to build the tool, cache the result on its version:

```yaml
env:
  NEXTEST_VERSION: 0.9.151

steps:
  - uses: actions/cache@v6
    id: nextest
    with:
      path: ~/.cargo/bin/cargo-nextest
      key: cargo-nextest-${{ env.NEXTEST_VERSION }}-${{ runner.os }}-${{ runner.arch }}
  - if: steps.nextest.outputs.cache-hit != 'true'
    run: cargo install --locked cargo-nextest --version "$NEXTEST_VERSION"
```

- The key holds the exact version plus OS and architecture, because the binary is platform-specific. Bumping the version misses the cache and builds once.
- `cache-hit` is true only on an exact key match, so the build step runs only when the binary isn't there.
- `--locked` builds with the tool's own lockfile, so the cached binary matches a fresh build.

### Playwright browsers

```yaml
  - name: Read the Playwright version
    id: playwright
    run: echo "version=$(npx playwright --version | cut -d' ' -f2)" >> "$GITHUB_OUTPUT"
  - uses: actions/cache@v6
    with:
      path: ~/.cache/ms-playwright
      key: playwright-${{ runner.os }}-${{ runner.arch }}-${{ steps.playwright.outputs.version }}
  - run: npx playwright install --with-deps chromium
```

- Each Playwright release pins its own browser builds, so the key follows the installed Playwright version. VS Code read the version from the lockfile and included the install arguments in the key too.
- Keep the install step after the restore. On a hit it finds the browsers and downloads nothing, and `--with-deps` still installs the OS packages, which the cache can't hold. On a miss it downloads as before.
- `~/.cache/ms-playwright` is the Linux path. Set `PLAYWRIGHT_BROWSERS_PATH` to one directory if you run on several operating systems.
- Run these steps after your dependency install, so `npx` finds the project's Playwright.

## Keep it safe

- **Never key on a floating version.** A cache keyed on `latest` freezes whatever version was current when it was saved, while the logs suggest you're up to date.
- **Cache poisoning.** A cached binary runs with the job's permissions and secrets. Pull request runs can only write their own scope, so the risk is a low-trust workflow writing the default branch's scope: leave `pull_request_target` and `workflow_run` jobs read-only, and fill tool caches from pushes to main, as VS Code does for Playwright. Keep checksum verification on the download path for misses.
- **Cold runs.** The first run after a version bump downloads or compiles everything. Make sure the job's `timeout-minutes` leaves room for that; Shopify raised a 10-minute limit to 20 when a cold browser download exceeded it.
- **Misses still need the network.** Keep retries on the download step for cache misses (see [resilient network calls](https://berrybox.io/playbooks/flaky-tests/resilient-network.md)).
- **Size.** Browsers take hundreds of megabytes per OS and version, and every combination counts toward the repository's 10 GB cache. Install only the browsers your tests use.
- **Required checks.** No job or check changes name, and a cache miss slows a job instead of failing it.

## Verify

- Compare the tool step's p50 in the long-pole step table with the [baseline](https://berrybox.io/playbooks/baseline.md), counting the new restore step's time. If restore plus install isn't clearly faster than the old download, remove the cache.
- Over the next week or two, check that reruns caused by tool downloads drop.
- Confirm the job logs the tool version you pinned, the same tests ran, and the same checks reported.

## Sources

- Uber: [submitqueue: resolve a downloaded prebuilt protoc in Bazel instead of compiling protoc and abseil](https://github.com/uber/submitqueue/pull/165). A cold make test after bazel clean went from about 84 seconds to about 11, with the same 35 tests passing.
- Microsoft: [vscode: restore Playwright browsers from a cache keyed on the pinned Playwright version and warmed on main](https://github.com/microsoft/vscode/pull/343387)
- Shopify: [checkout-kit: cache Playwright Chromium and keep the install command after the restore](https://github.com/Shopify/checkout-kit/pull/972)
- Bun: [bun: cache the dylint binaries and driver, keyed on the dylint version and the pinned lint revision](https://github.com/oven-sh/bun/pull/38459)
