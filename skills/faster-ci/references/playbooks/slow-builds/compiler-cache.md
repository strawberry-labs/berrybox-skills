# Keep compiler and build caches between runs

Restore the compiler's and build tool's caches on every run and save them only from the default branch, so a small change recompiles only the units it touched.

- Playbook: [Build less, and build it faster](https://berrybox.io/playbooks/slow-builds.md)
- Saves: wait time and runner minutes
- Risk: low
- Web page: https://berrybox.io/playbooks/slow-builds/compiler-cache

## Signals in your baseline

- Compile or build steps take most of the long-pole job, and a one-line change builds about as slowly as a large one.
- The workflow caches package downloads but no build output: no `target/`, `GOCACHE`, ccache or sccache directory, Gradle build cache, `.turbo` or `.nx/cache`.
- Build logs show cache misses on packages the change didn't touch, for example Turborepo's `cache miss, executing` or Gradle tasks that never show `FROM-CACHE`.
- `actions/setup-go` reports an exact cache hit on every run, so its build cache hasn't been saved since `go.sum` last changed.

## Why it works

A rebuild on a developer laptop is fast because the compiler and build tool skip every crate, package, object file or task whose inputs haven't changed. A fresh CI runner has none of that state, so each run compiles the whole tree. Restore the last build's cache and CI gets the same reuse: only what your change touched compiles.

Content-keyed caches (ccache, sccache, the Go build cache, Gradle's build cache, Turborepo and Nx) look up each unit by a hash of its inputs. An entry is reused only when nothing it depends on changed, as long as the tool knows every input.

## Apply it

Use one pattern everywhere: restore on every run, save only from pushes to the default branch, and key on the toolchain, the lockfile and the commit. Pull requests can read default-branch caches, so they start warm without filling the repository's cache quota with entries no other branch can read.

### Go

`actions/setup-go` caches by default, but its key changes only with `go.sum`, so after the first save every run is an exact hit and the build cache never updates. Manage the cache yourself:

```yaml
name: go
on:
  pull_request:
  push:
    branches: [main]

permissions:
  contents: read

jobs:
  test:
    runs-on: ubuntu-latest
    timeout-minutes: 20
    steps:
      - uses: actions/checkout@v7
      - id: go
        uses: actions/setup-go@v7
        with:
          go-version-file: go.mod
          cache: false
      - id: dirs
        run: |
          echo "build=$(go env GOCACHE)" >> "$GITHUB_OUTPUT"
          echo "mod=$(go env GOMODCACHE)" >> "$GITHUB_OUTPUT"
      - uses: actions/cache/restore@v6
        with:
          path: |
            ${{ steps.dirs.outputs.build }}
            ${{ steps.dirs.outputs.mod }}
          key: go-${{ runner.os }}-${{ runner.arch }}-${{ steps.go.outputs.go-version }}-${{ hashFiles('**/go.sum') }}-${{ github.sha }}
          restore-keys: |
            go-${{ runner.os }}-${{ runner.arch }}-${{ steps.go.outputs.go-version }}-${{ hashFiles('**/go.sum') }}-
            go-${{ runner.os }}-${{ runner.arch }}-${{ steps.go.outputs.go-version }}-
      - run: go build ./... && go test ./...
      - if: github.ref == 'refs/heads/main'
        uses: actions/cache/save@v6
        with:
          path: |
            ${{ steps.dirs.outputs.build }}
            ${{ steps.dirs.outputs.mod }}
          key: go-${{ runner.os }}-${{ runner.arch }}-${{ steps.go.outputs.go-version }}-${{ hashFiles('**/go.sum') }}-${{ github.sha }}
```

- `github.sha` makes every default-branch save a new entry, because a cache key can't be overwritten. The `restore-keys` prefixes pick the newest entry for the same Go version.
- Replace `main` with your default branch.

### Rust, C and C++

For Rust, `Swatinem/rust-cache` caches `~/.cargo` and compiled dependencies, keys on `Cargo.lock` and the toolchain, and sets `CARGO_INCREMENTAL=0`, because incremental artifacts cost CI time and cache space without paying off:

```yaml
      - uses: Swatinem/rust-cache@d1527c8f67ef9af357290475d4af4b0fab8f12e0 # v2.9.3
        with:
          save-if: ${{ github.ref == 'refs/heads/main' }}
      - run: cargo test --locked
```

When your own crates dominate compile time, or for C and C++, use a compiler wrapper. sccache with `SCCACHE_GHA_ENABLED=true` stores each compilation in the Actions cache. ccache needs `CCACHE_DIR` cached with the restore and save pair above, and CMake projects pass `-DCMAKE_C_COMPILER_LAUNCHER=ccache -DCMAKE_CXX_COMPILER_LAUNCHER=ccache`.

### Gradle

Set `org.gradle.caching=true` in `gradle.properties` and let `setup-gradle` persist Gradle User Home, which includes the local build cache. It writes only from the default branch unless you change `cache-read-only`.

```yaml
      - uses: gradle/actions/setup-gradle@8da46b539cd8fe6ab27ca75128919a18d757604c # v6.4.1
      - run: ./gradlew build
```

Its default cache provider is proprietary (free for public repositories, a free preview for private ones). `cache-provider: basic` is MIT-licensed but keys only on build files, so it reuses less.

### Turborepo and Nx

Persist `.turbo/cache` or `.nx/cache` with the restore and save pair, or use the tool's remote cache. Then declare inputs. Without `inputs`, Turborepo hashes every tracked file in a package, so editing a test or a README rebuilds it. Start from the defaults and subtract:

```json
{
  "$schema": "https://turborepo.dev/schema.json",
  "tasks": {
    "build": {
      "dependsOn": ["^build"],
      "inputs": ["$TURBO_DEFAULT$", "!**/*.md", "!**/*.test.ts"],
      "outputs": ["dist/**"]
    }
  }
}
```

In Nx, the same idea is a `production` named input that excludes spec files. Keep secrets out of a task's `env` list: their values feed the hash, so rotating a key invalidates every package.

## Keep it safe

- **Untrusted writers.** Caches saved by `pull_request` runs are visible only to that pull request. `pull_request_target` and `workflow_run` workflows run in the default branch's cache scope, so never build pull request code in them: one pull request could poison the cache every branch restores.
- **Release builds.** Build releases without the shared compiler cache, or only from entries default-branch pushes wrote. Sentry skips its Nx cache on release branches.
- **Missing inputs.** A task that reads an undeclared file, tool version or environment variable replays a stale output. Run an uncached build on a schedule; any difference points to a missing input.
- **Go test results.** Restoring `GOCACHE` also restores Go's test cache, so unchanged packages report `(cached)`. Add `-count=1` to `go test` if tests depend on things Go can't track, such as a database or the network.
- **Cache size.** The repository limit is 10 GB by default. GitHub deletes entries unread for 7 days and, over the limit, evicts the least recently used. Per-commit compiler caches can push out dependency caches, so check `gh cache list --sort size_in_bytes`, cap ccache and sccache sizes, and save from one job per platform.
- **Secrets.** Gradle's configuration cache can hold secret values. Set `cache-encryption-key` if you cache it.

## Verify

- After one default-branch run seeds the cache, push a one-file change to a test pull request. The restore step should log a hit on a default-branch key.
- Compare the compile step's p50 with the [baseline](https://berrybox.io/playbooks/baseline.md) over five or more runs, and report cold and warm runs separately.
- Check hit rates where the tool reports them: `sccache --show-stats`, `ccache --show-stats`, Turborepo's `Cached:` summary line, Gradle tasks marked `FROM-CACHE`.
- Confirm the test step reports the same number of tests as before, and that a scheduled uncached build still passes.

## Sources

- LinkedIn: [LinkedIn Engineering: a shared Gradle remote build cache that CI writes and developer machines read](https://engineering.linkedin.com/blog/2019/productivity-at-scale--how-we-improved-build-time-with-gradle-bu). Build time fell 30% on LinkedIn's two largest Java applications, Voyager-API and the Android app.
- Sentry: [Sentry blog: cache sentry-javascript build tasks with Nx and declare their inputs](https://blog.sentry.io/reduce-ci-time-with-nx-caching/). Median build time went from about 8 minutes to about 6, and the fastest CI runs from about 20 minutes to about 13.
- OpenAI: [openai-go: give lint its own Go build and analysis cache, keyed on every go.mod and go.sum, the Go version and the config](https://github.com/openai/openai-go/pull/996)
- Ramp: [ramp-cli: persist the Nuitka ccache with actions/cache and refresh it on every push to main](https://github.com/ramp-public/ramp-cli/commit/4fec456d52fd03f85e1b96c94e075d22b5306c51)
