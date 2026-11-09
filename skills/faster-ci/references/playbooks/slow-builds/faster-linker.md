# Link with LLD or mold, and keep heavy LTO out of CI test builds

Link Rust and C/C++ builds with LLD or mold instead of the platform's default linker, and save full link-time optimization for release builds, where the runtime gain pays for the minutes.

- Playbook: [Build less, and build it faster](https://berrybox.io/playbooks/slow-builds.md)
- Saves: wait time and runner minutes
- Risk: low
- Web page: https://berrybox.io/playbooks/slow-builds/faster-linker

## Signals in your baseline

- `Cargo.toml` sets `lto = true` or `lto = "fat"` in a profile that pull request or test builds use.
- Rust builds for arm64 Linux or Windows MSVC, which still use the platform linker by default, or pin a toolchain older than 1.90 on x86_64 Linux.
- C or C++ builds link with GNU `ld`: no `-fuse-ld=` flag and no `CMAKE_LINKER_TYPE`.
- Release builds are the long pole of release runs, and their logs spend most of that time in the final code generation and link.

## Why it works

The link step runs at the end of every build, even when a cache restored everything else. GNU `ld`, the default on most Linux systems, links on a single thread and slows down as binaries grow. The Rust project found that roughly half of a debug ripgrep build on Linux was spent in the linker. LLD and mold spread the work across cores and finish the same link much faster.

Link-time optimization (LTO) moves optimization into the link. Fat LTO merges the whole program into one unit, so the link becomes the long pole. ThinLTO keeps most of the cross-crate gain at a fraction of the cost, and builds that only run tests don't need LTO at all.

## Apply it

### Rust on Linux

Rust 1.90 and later already link with LLD on `x86_64-unknown-linux-gnu`. Check `rustc --version` and your `rust-toolchain.toml`. Other targets, including arm64 Linux, still use the platform linker unless you opt in:

```yaml
name: rust-arm64
on:
  pull_request:
  push:
    branches: [main]

permissions:
  contents: read

jobs:
  test:
    runs-on: ubuntu-24.04-arm
    timeout-minutes: 30
    env:
      CARGO_TARGET_AARCH64_UNKNOWN_LINUX_GNU_RUSTFLAGS: -C link-arg=-fuse-ld=mold
    steps:
      - uses: actions/checkout@v7
      - run: sudo apt-get update && sudo apt-get install -y mold
      - run: cargo test --locked
```

- The target-specific variable applies the flag only to arm64 Linux builds in CI, so laptops without mold keep working.
- `-fuse-ld=mold` goes to the C compiler that Rust uses as its linker driver. GCC on Ubuntu 24.04 supports it.
- To make it the default for everyone, put the same flag under `[target.aarch64-unknown-linux-gnu]` as `rustflags` in `.cargo/config.toml`.

On Windows, Rust ships LLD as `rust-lld.exe`. Set `linker = "rust-lld.exe"` under `[target.x86_64-pc-windows-msvc]` in `.cargo/config.toml`. Codex does the same for its Windows releases by pointing `CARGO_TARGET_<TRIPLE>_LINKER` at that file.

Debug info makes up much of what a debug build links. Set `CARGO_PROFILE_DEV_DEBUG: line-tables-only` in CI to keep file and line numbers in backtraces and drop the rest.

### C and C++

```yaml
      - run: sudo apt-get update && sudo apt-get install -y mold
      - run: cmake -B build -DCMAKE_BUILD_TYPE=Release -DCMAKE_LINKER_TYPE=MOLD
      - run: cmake --build build --parallel
```

`CMAKE_LINKER_TYPE` needs CMake 3.29 or newer. With older CMake or plain Makefiles, add `-fuse-ld=mold` (or `-fuse-ld=lld` after installing `lld`) to `LDFLAGS`.

### LTO only where it pays

```toml
[profile.release]
lto = "thin"

[profile.ci]
inherits = "release"
lto = "off"
```

If releases use fat LTO (`lto = true`), measure ThinLTO. Codex's release build got 40% faster for a 7.63% larger binary and runtime changes under 1%. Build pull request and test jobs with `cargo build --profile ci`, the way Materialize builds its tests without LTO and keeps it for releases.

## Keep it safe

- **Release binaries.** A new linker or LTO setting changes the shipped binary. Before switching release builds, compare binary size, startup time and one real benchmark, and run the full suite against the release artifact.
- **Flag precedence.** If the workflow sets `RUSTFLAGS`, Cargo ignores `CARGO_TARGET_<TRIPLE>_RUSTFLAGS` and config `rustflags`. Put all flags in one place.
- **Linker everywhere.** A flag in `.cargo/config.toml` makes mold a requirement for every machine that builds that target, including dev containers and release jobs.
- **One cold run.** Changing linker flags or profiles invalidates Cargo's fingerprints and most cache keys, so the first run rebuilds everything. Compare warm runs.
- **Escape hatch.** If LLD breaks a link on x86_64 Linux, for example a linker script that relies on GNU `ld`, `-C linker-features=-lld` restores the system linker.
- **Required checks.** Nothing here renames jobs. If you add a `ci` profile, confirm release jobs still build with `--release`.

## Verify

- Confirm the linker: `readelf -p .comment` on the built binary lists `mold` or `Linker: LLD`.
- Compare the build step p50 with the [baseline](https://berrybox.io/playbooks/baseline.md) over five or more warm runs. In `cargo build --timings`, the final binary units should shrink the most.
- The same number of tests passes, and release artifacts pass the same smoke tests with their size change recorded in the pull request.

## Sources

- Rust project: [Rust blog: link with rust-lld by default on x86_64 Linux nightly](https://blog.rust-lang.org/2024/05/17/enabling-rust-lld-on-linux/). For a debug build of ripgrep, linking got 7x faster, a 40% reduction in end-to-end compilation time.
- OpenAI: [codex: switch release binaries from fat LTO to ThinLTO](https://github.com/openai/codex/pull/23710). A clean codex-cli release build went from 2073.893 seconds to 1243.172 seconds, a 40.06% improvement.
- OpenAI: [codex: link Windows release builds with LLD](https://github.com/openai/codex/pull/27315)
- Materialize: [Materialize blog: turn off LTO for test builds and keep it for releases](https://materialize.com/blog/speeding-up-materialize-ci/). LTO added about 20 minutes to incremental builds while making Materialize only about 10% faster at runtime.
