# Profile the build before you optimize it

Record where build time goes with the compiler's and build tool's own profilers on a CI runner, then fix the crate, header, type or dependency that costs the most instead of guessing.

- Playbook: [Build less, and build it faster](https://berrybox.io/playbooks/slow-builds.md)
- Saves: wait time and runner minutes
- Risk: low
- Web page: https://berrybox.io/playbooks/slow-builds/profile-the-build

## Signals in your baseline

- The build step is still the long pole after caching, and nobody can name which crate, package, target or header costs the most.
- No workflow or script in the repository produces a build profile: no `--timings`, `--extendedDiagnostics`, `--generateTrace`, Gradle `--profile`, Bazel `--profile` or `-ftime-trace`.
- The build step's p50 in the baseline is far above what the size of a typical change would suggest, or it has grown over recent months.

## Why it works

Build time is rarely spread evenly. It piles up in a few places: a crate full of macro-generated code, a header that half the codebase includes, a dependency pulled in for one tool, a type the checker struggles with, or one target that every other target waits on. Compilers and build tools can record exactly where their time goes. A profile turns "the build is slow" into a ranked list, so you fix the biggest item, measure again, and stop when the build is no longer the long pole.

## Apply it

Profile on the same runner type CI uses. A laptop has different cores, disks and cache state, so its numbers mislead. A manual workflow keeps profiling out of pull requests:

```yaml
name: build-profile
on:
  workflow_dispatch:

permissions:
  contents: read

jobs:
  profile:
    runs-on: ubuntu-latest
    timeout-minutes: 60
    steps:
      - uses: actions/checkout@v7
      - run: cargo build --release --locked --timings
      - uses: actions/upload-artifact@v7
        with:
          name: cargo-timings
          path: target/cargo-timings/
          retention-days: 7
```

- Start it with `gh workflow run build-profile.yml --ref <branch>`. The file must exist on the default branch before GitHub lets you dispatch it.
- This profiles a cold build. Restore your build cache first if you want to see what a typical pull request pays.
- Swap the `cargo` line for your ecosystem's command below and point the upload at its report.

### Rust

`cargo build --timings` writes `cargo-timing.html`: one bar per crate, plus a chart of how many crates compile at once. Look for long bars while few others run. Those crates hold everything else back, so split them or trim what they depend on. To see inside one crate, use nightly: `cargo +nightly rustc -p <crate> -- -Z time-passes`. Codex used it to measure what `#[async_trait]` cost its tool handlers. `cargo tree --duplicates` lists dependencies compiled in more than one version.

### TypeScript

`npx tsc --noEmit --extendedDiagnostics` prints file counts, memory and time per phase (parse, bind, check). `npx tsc --noEmit --generateTrace trace` writes a trace you can open in Perfetto to find the files and types that take longest to check.

### Gradle

`./gradlew build --profile` writes an HTML report under `build/reports/profile/` with configuration time and time per task. A Build Scan (`--scan`) shows more, but it uploads build data to Gradle's servers, so get approval before using it on private code. If the daemon runs short of memory, garbage collection eats build time: size the heap in `org.gradle.jvmargs` to fit the runner.

### Bazel

`bazel build //... --profile=profile.json.gz` records every action, and `bazel analyze-profile profile.json.gz` summarizes the critical path. To find out why a heavy dependency is in the build at all, run `bazel query 'allpaths(//main:app, @dep//:target)'`. Sorbet used that to find that only buildifier needed protoc.

### C and C++

Clang's `-ftime-trace` writes a JSON trace per object file that splits time between header parsing, template instantiation and code generation. Figma tracked the bytes each file sends to the compiler after preprocessing and cut includes from its largest files.

Then pick the play that matches the hot spot: [a faster linker](https://berrybox.io/playbooks/slow-builds/faster-linker.md) when the final link dominates, [compiler caches](https://berrybox.io/playbooks/slow-builds/compiler-cache.md) when unchanged code recompiles, or [a bigger runner](https://berrybox.io/playbooks/runners/bigger-runner.md) when every core stays busy for the whole build.

## Keep it safe

- **Keep it off the gate.** Profiling flags slow the build, and nightly-only flags can break on any toolchain update. Run them in a manual or scheduled workflow, never in a required check.
- **Treat profiles as internal.** Traces and timing reports contain file paths, target names and dependency lists. Keep retention short, remember that anyone who can read a public repository can download its artifacts, and don't publish Build Scans without approval.
- **Review the fix like any change.** Removing a dependency or restructuring code to compile faster changes behavior risk. Run the full suite, and compare profiles against the same base commit, as Codex did.
- **Least privilege.** The profiling workflow needs only `contents: read`.

## Verify

- After each fix, rerun the same profile on the same runner type and compare the specific number you targeted: the crate's bar, the check phase, the task time or the critical path.
- Then compare the build step's p50 in normal CI runs with the [baseline](https://berrybox.io/playbooks/baseline.md) over five or more runs.
- Confirm the same tests run and pass, and that the build produces the same artifacts.

## Sources

- OpenAI: [codex: replace async_trait on tool handlers with native async traits after -Z time-passes showed the cost](https://github.com/openai/codex/pull/16630). On a clean codex-core rebuild, rustc's total time dropped from 187.15s to 68.98s (-63.1%).
- Sorbet: [sorbet: drop the protoc dependency from the main binary after bazel query allpaths showed only buildifier needed it](https://github.com/sorbet/sorbet/pull/10124). A debug build of //main:sorbet went from 3:57.62 to 2:55.61.
- Figma: [Figma blog: measure the bytes each C++ file sends to the compiler and remove unnecessary includes](https://www.figma.com/blog/speeding-up-build-times/). Compiled bytes fell 31% and cold build time fell 25%.
