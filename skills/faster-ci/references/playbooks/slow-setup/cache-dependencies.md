# Cache package downloads, keyed on the lockfile

Restore the package manager's download store from a key that hashes the lockfile, check out before you hash, and let only trusted default-branch runs write the cache that every pull request reads.

- Playbook: [Get setup off the clock](https://berrybox.io/playbooks/slow-setup.md)
- Saves: wait time and runner minutes
- Risk: low
- Web page: https://berrybox.io/playbooks/slow-setup/cache-dependencies

## Signals in your baseline

- Install steps such as npm ci, pnpm install, pip install or go mod download take 30 seconds or more in the long-pole step table.
- setup-node, setup-python, setup-go or setup-java run without their cache input, and no actions/cache step covers the package store.
- An actions/cache key has no hashFiles() of a lockfile, or the cache step runs before actions/checkout.
- Job logs show "Cache not found" on most runs even though the lockfile rarely changes.

## Why it works

Most install time goes to downloading packages that haven't changed since the last run. Every package manager keeps those downloads in a local store (`~/.npm`, the pnpm store, `~/.cache/pip`, the Go module cache), and a fresh runner starts with that store empty. If you save the store at the end of a run and restore it at the start of the next one, the install resolves from local disk and touches the network only for what changed.

Key the cache on a hash of the lockfile. The same lockfile means the same packages, so an unchanged lockfile gets an exact hit, and a changed one gets a new entry. Cache the download store rather than the installed tree (`node_modules`, a virtualenv): the install command still runs, so it still enforces the lockfile, and a partial or stale restore can only cost time, never pick versions.

## Apply it

Put `actions/checkout` before any step that computes a cache key. `hashFiles()` reads the workspace, and before checkout it finds no lockfile and returns an empty string, so every run shares a key that never changes.

### Node with pnpm or npm

```yaml
steps:
  - uses: actions/checkout@v7
  - uses: pnpm/action-setup@v6
  - uses: actions/setup-node@v7
    with:
      node-version: 24
      cache: pnpm
  - run: pnpm install --frozen-lockfile
```

- `pnpm/action-setup` reads the pnpm version from `packageManager` in `package.json` (or set its `version` input). It must run before `setup-node`, which asks pnpm where its store lives.
- `cache: pnpm` keys the store on `pnpm-lock.yaml`. Use `cache-dependency-path` when the lockfile isn't at the repository root.
- For npm, drop the pnpm step, set `cache: npm` and run `npm ci`. setup-node also caches npm on its own when `packageManager` names npm.

### Python

```yaml
  - uses: actions/setup-python@v7
    with:
      python-version: "3.14"
      cache: pip
      cache-dependency-path: requirements*.txt
  - run: pip install -r requirements.txt -r requirements-dev.txt
```

With uv, `astral-sh/setup-uv` turns its cache on by default on GitHub-hosted runners, keyed on `uv.lock` and the other dependency files it finds. It has no floating major tag, so pin a release such as `astral-sh/setup-uv@v10.3.3`.

### Go

`actions/setup-go` caches the module and build caches by default, keyed on `go.sum`. Set `go-version-file: go.mod`, and set `cache-dependency-path: "**/go.sum"` when `go.sum` isn't at the root, which is the fix Uber made in tchannel-go.

### Anything else

When no setup action covers the tool, or you need control of the key, use `actions/cache` directly:

```yaml
  - uses: actions/cache@v6
    with:
      path: ~/.npm
      key: ${{ runner.os }}-npm-${{ hashFiles('**/package-lock.json') }}
      restore-keys: |
        ${{ runner.os }}-npm-
```

- On a miss, `restore-keys` restores the newest entry whose key starts with that prefix, so a lockfile change downloads only the difference.
- Entries are immutable. A job that restored through `restore-keys` saves a new entry under the exact key when it succeeds.
- Put `runner.os` (and `runner.arch` if you build on several) in every key, because stores hold platform-specific files.

For Java, `actions/setup-java` takes `cache: gradle` or `cache: maven`.

## Keep it safe

- **Cache poisoning.** A restored cache is code your build runs. Pull request runs save to the pull request's merge ref, where only that pull request can read them, but default-branch entries are readable from every branch. GitHub gives `pull_request_target`, `issue_comment` and `workflow_run` runs read-only cache access by default; don't override that with `cache-mode: write`, and let a push-triggered workflow on the default branch keep the cache warm.
- **Secrets.** Anyone who can open a pull request can read the base branch's caches. Never cache `.npmrc` or `pip.conf` files that hold tokens, or any directory a login step writes credentials into.
- **Correctness.** Always run the frozen install after the restore (`npm ci`, `pnpm install --frozen-lockfile`). The lockfile, not the cache, decides versions.
- **Size.** A repository gets 10 GB of cache by default. Entries unused for 7 days are evicted, and when the total passes the limit GitHub evicts the least recently used. See [drop slow caches](https://berrybox.io/playbooks/slow-setup/drop-slow-caches.md) if usage gets close.
- **Required checks.** This play renames no job, and a cache service error only logs a warning, so checks report as before. Leave `fail-on-cache-miss` off.

## Verify

- Push twice to a test pull request without touching the lockfile. The second run should log `Cache restored from key`, and the install step's p50 should drop against the [baseline](https://berrybox.io/playbooks/baseline.md).
- Count the restore step's time against what the install saved. If the restore costs more than the download did, remove the cache.
- Check that the same number of tests ran and the same checks reported.

## Sources

- Linear: [linear: cache the pnpm store and npx tool downloads, keyed on the lockfile and tool version](https://github.com/linear/linear/pull/1130)
- Uber: [tchannel-go: check out before setup-go and point its cache at the nested go.sum](https://github.com/uber/tchannel-go/pull/935)
- Shopify: [checkout-kit: add Gradle and CocoaPods caches to the React Native jobs](https://github.com/Shopify/checkout-kit/pull/182)
- Spotify: [target-determinator: cache Bazel downloads, with pull request runs restore-only](https://github.com/spotify/target-determinator/pull/15)
