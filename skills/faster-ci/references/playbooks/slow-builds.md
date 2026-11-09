# Build less, and build it faster

Carry compiler, build tool and Docker layer caches between runs, build each architecture natively, move lint and type checks to native tools and link faster, guided by a profile of where build time goes.

Web page: https://berrybox.io/playbooks/slow-builds

## Signals in your baseline

- Compile, bundle, Docker build, lint or type-check steps take most of the long-pole job.
- A one-line change builds about as slowly as a large one, because nothing from the previous build is reused.
- An image workflow builds arm64 under QEMU with `docker/setup-qemu-action`.
- Lint and type checks run TypeScript below version 7, type-aware ESLint rules, flake8 or isort.

A fresh runner remembers nothing, so every run compiles the same crates, rebuilds the same Docker layers and lints with the same slow tools as the run before it. These plays carry finished work over from earlier runs, take emulation and slow tools off the path and shorten the final link. They change how CI builds, not what it checks, so the same code gets the same verdict sooner.

## Confirm it in your baseline

- In **Steps inside the long-pole jobs**, add up the compile, `docker build`, lint and type-check steps. If they take more than half the job, start here.
- Compare the build step on a one-line pull request with the same step on a large one. Similar times mean nothing carries over between runs.
- Search the workflow files for `setup-qemu-action`, `docker/build-push-action` without `cache-from`, and `cargo`, `go build`, `gradle`, `turbo` or `nx` steps with no cache for build output.
- Check `package.json` for `typescript` below 7, the ESLint config for `parserOptions.project`, and the workflows for flake8 or isort steps.

## Order of work

Start with [compiler and build caches](https://berrybox.io/playbooks/slow-builds/compiler-cache.md) and [Docker layer caching](https://berrybox.io/playbooks/slow-builds/docker-layer-cache.md). Both are low risk and pay off on every later run. If an image build runs under QEMU, [build each architecture natively](https://berrybox.io/playbooks/slow-builds/native-arch-builds.md) next: Spotify's emulated build took 2 hours 28 minutes, and the native one about 17. [Native lint and type-check tools](https://berrybox.io/playbooks/slow-builds/native-tools.md) need a rule-by-rule check, so give them their own pull request. Switch to [a faster linker](https://berrybox.io/playbooks/slow-builds/faster-linker.md) when Rust or C++ links dominate. If the build is still slow and you can't say why, [profile it](https://berrybox.io/playbooks/slow-builds/profile-the-build.md) before you change anything else.

## Plays

- [Keep compiler and build caches between runs](https://berrybox.io/playbooks/slow-builds/compiler-cache.md): Restore the compiler's and build tool's caches on every run and save them only from the default branch, so a small change recompiles only the units it touched. Saves wait time and runner minutes; low risk.
- [Reuse Docker layers across runners](https://berrybox.io/playbooks/slow-builds/docker-layer-cache.md): Export BuildKit's layer cache to the GitHub Actions cache or a registry, and order the Dockerfile so a source change rebuilds only the layers that come after it. Saves wait time and runner minutes; low risk.
- [Build each architecture on a native runner instead of under QEMU](https://berrybox.io/playbooks/slow-builds/native-arch-builds.md): Build the amd64 and arm64 images in parallel on matching runners and merge them into one multi-arch tag, instead of compiling arm64 under QEMU on an x86 runner. Saves wait time and runner minutes; medium risk.
- [Move lint and type checks to native tools without losing rules](https://berrybox.io/playbooks/slow-builds/native-tools.md): Type-check with TypeScript 7's native compiler and lint with Oxlint or Ruff, after you map every rule you run today and prove the new setup still fails on the problems the old one caught. Saves wait time and runner minutes; medium risk.
- [Link with LLD or mold, and keep heavy LTO out of CI test builds](https://berrybox.io/playbooks/slow-builds/faster-linker.md): Link Rust and C/C++ builds with LLD or mold instead of the platform's default linker, and save full link-time optimization for release builds, where the runtime gain pays for the minutes. Saves wait time and runner minutes; low risk.
- [Profile the build before you optimize it](https://berrybox.io/playbooks/slow-builds/profile-the-build.md): Record where build time goes with the compiler's and build tool's own profilers on a CI runner, then fix the crate, header, type or dependency that costs the most instead of guessing. Saves wait time and runner minutes; low risk.
