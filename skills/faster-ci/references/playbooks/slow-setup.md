# Get setup off the clock

Cache downloads on lockfile keys, fetch only the history a job reads, install only what it runs and bake stable tools into an image, so each job reaches its real work in seconds.

Web page: https://berrybox.io/playbooks/slow-setup

## Signals in your baseline

- Checkout, setup-*, dependency install and cache steps add up to a quarter or more of the long-pole job.
- Every shard or matrix entry repeats the same install and download steps.
- Workflows install packages with no cache, or check out with fetch-depth 0 in jobs that only build and test.
- Cache restore steps or the Post steps that save caches take tens of seconds.

Every job pays an entry fee before it does anything useful: a fresh runner, a clone, a toolchain, a package install. On a three-minute job, ninety seconds of setup is half the bill, and the fee repeats in every shard and matrix entry. These plays cut the fee without changing what your tests check, which makes them a safe second step after [Wasted runs](https://berrybox.io/playbooks/wasted-runs.md).

## Confirm it in your baseline

- In **Steps inside the long-pole jobs**, add up the share of checkout, `setup-*` actions, install commands and cache steps. Above about 25 percent, setup is worth fixing before anything else in that job.
- Look for steps whose names start with `Post`, such as `Post Run actions/cache@v6`. Caches are saved there, and a save that takes 30 seconds on every run is a cost, not a speedup.
- Multiply: if eight test shards each spend a minute installing, every run pays eight runner minutes for setup alone.
- Search the workflow files for `fetch-depth: 0`, `apt-get install`, `curl` downloads and install commands that run without a cache.

## Order of work

Start with [caching dependencies](https://berrybox.io/playbooks/slow-setup/cache-dependencies.md) and [shallow checkouts](https://berrybox.io/playbooks/slow-setup/shallow-checkout.md). Both are low risk and take minutes to apply. Then [scope installs](https://berrybox.io/playbooks/slow-setup/install-only-what-runs.md) and [cache tool downloads](https://berrybox.io/playbooks/slow-setup/cache-tool-downloads.md) for jobs that still spend most of their time installing. [Prebuilt images](https://berrybox.io/playbooks/slow-setup/prebake-images.md) cost the most to maintain, so save them for installs that repeat in many jobs and rarely change. Finish with [drop slow caches](https://berrybox.io/playbooks/slow-setup/drop-slow-caches.md): audit every cache, including the ones you just added, and remove the ones that lose time.

## Plays

- [Cache package downloads, keyed on the lockfile](https://berrybox.io/playbooks/slow-setup/cache-dependencies.md): Restore the package manager's download store from a key that hashes the lockfile, check out before you hash, and let only trusted default-branch runs write the cache that every pull request reads. Saves wait time and runner minutes; low risk.
- [Fetch only the history and files a job needs](https://berrybox.io/playbooks/slow-setup/shallow-checkout.md): Keep actions/checkout at its default single commit, give the few jobs that diff or version just the history they read, and use blobless or sparse checkouts for jobs that need commit history or a few folders but not every file. Saves wait time and runner minutes; low risk.
- [Install only the packages and tools each job uses](https://berrybox.io/playbooks/slow-setup/install-only-what-runs.md): Scope each job's install to the workspace packages and dependency groups it actually runs, and skip the full install in jobs that only need one small tool. Saves wait time and runner minutes; medium risk.
- [Bake stable dependencies into the runner or container image](https://berrybox.io/playbooks/slow-setup/prebake-images.md): Move the tools and system packages that every job installs and that rarely change into a prebuilt container or runner image, rebuilt on a schedule and whenever its inputs change. Saves wait time and runner minutes; medium risk.
- [Cache browsers, toolchains and CLI downloads](https://berrybox.io/playbooks/slow-setup/cache-tool-downloads.md): Keep downloaded browsers, compilers and CLIs between runs in a cache keyed on the exact tool version, or swap a compile-from-source step for a prebuilt binary, when the download is slow, flaky or rate-limited. Saves wait time and runner minutes; low risk.
- [Remove caches that take longer than the work they skip](https://berrybox.io/playbooks/slow-setup/drop-slow-caches.md): Time each cache's restore and save against the work it skips, delete the ones that lose, save from the default branch only, and keep pull request and merge queue writes from evicting the entries main relies on. Saves wait time and runner minutes; low risk.
