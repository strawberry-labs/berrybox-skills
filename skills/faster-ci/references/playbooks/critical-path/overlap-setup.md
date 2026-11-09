# Run independent steps at the same time inside a job

In the long-pole job, start independent steps such as image pulls, dependency installs, per-target builds and packaging together, wait for them before the step that needs their results, and keep every failure visible.

- Playbook: [Shorten the path that ends the run](https://berrybox.io/playbooks/critical-path.md)
- Saves: wait time
- Risk: low
- Web page: https://berrybox.io/playbooks/critical-path/overlap-setup

## Signals in your baseline

- The long pole's rows in "Steps inside the long-pole jobs" show two or more slow steps in a row that don't use each other's output, such as an image pull followed by a dependency install.
- A step builds, compresses or uploads several targets one at a time in a loop.
- The long pole starts a container, database or emulator only after an unrelated install step has finished.

## Why it works

Steps in a job run one after another unless you say otherwise. An image pull waits on the network, a dependency install waits on the network and the disk, and a loop that compiles one target at a time leaves the other cores idle. When two steps don't use each other's output, starting them together makes the pair take as long as the slower step instead of the sum of both.

This shortens the run only in a job on the critical path, and only when the steps don't compete for the same resource. Two CPU-bound compiles on a 2-core runner won't finish sooner side by side.

## Apply it

### Parallel and background steps

GitHub Actions can run steps of one job concurrently. A `parallel` group starts its steps together and waits for all of them. A step with `background: true` keeps running while later steps start, until a `wait` step names it.

```yaml
jobs:
  e2e:
    runs-on: ubuntu-24.04
    steps:
      - uses: actions/checkout@v7
      - uses: actions/setup-node@v7
        with:
          node-version: 24
          cache: npm
      - parallel:
          - name: Pull service images
            run: docker compose -f compose.ci.yml pull --quiet
          - name: Install dependencies
            run: npm ci
      - name: Build
        id: build
        run: npm run build
        background: true
      - name: Start services
        run: docker compose -f compose.ci.yml up --detach --wait
      - wait: build
      - run: npm run test:e2e
```

- The `parallel` group ends with an implicit wait, so the build starts only after the pull and the install have both finished.
- The build runs in the background while the services start. `wait: build` blocks until it's done, and fails the job if the build failed.
- Outputs and environment changes from a background step, including `GITHUB_PATH` changes made by setup actions, become visible only after the `wait`.
- A job runs at most 10 background steps at once. Composite actions can't declare background steps.

These keywords arrived in June 2026. If you use self-hosted runners, check that their runner version supports them before you rely on them.

### Shell background jobs

Inside one `run` script, start a command with `&` and wait for its process ID:

```bash
docker compose -f compose.ci.yml pull --quiet &
pull_pid=$!
npm ci
wait "$pull_pid"
```

- `wait "$pull_pid"` returns the background command's exit status, so a failed pull fails the step. A bare `wait` with no arguments returns 0 even when a background command failed.

### Loops over targets

Replace a loop that handles one target at a time with a pool of workers:

```bash
find dist -name '*.tar' -print0 | xargs -0 -n 1 -P "$(nproc)" zstd -q -19 --rm
```

- `-P "$(nproc)"` runs one worker per core, and `xargs` exits with status 123 if any invocation failed, so the step still fails.
- Build tools have their own switches: `make -j"$(nproc)"`, `gradle --parallel` and Turborepo, which runs the tasks in one `turbo run lint typecheck` call concurrently. Cargo already compiles crates in parallel.

## Keep it safe

- Check every exit code. A background command nobody waits for can fail silently while the job goes green. Wait on native background steps explicitly where the result matters, and wait on each process ID in shell scripts.
- Don't overlap steps that write the same files. Two installs into one `node_modules`, two Gradle builds in one project directory, or a step that reads a directory another step is still writing can give corrupt or flaky results.
- Keep parallelism at or below the runner's cores (`nproc`) and watch memory. A runner that runs out of memory loses contact with GitHub, and the job fails with an infrastructure error instead of a clear message.
- Don't move credential setup, such as a registry login, into a background step that later steps depend on. Its environment changes appear only after the `wait`, so those steps would run unauthenticated.
- Job names don't change, so required checks keep matching.

## Verify

- In the branch baseline's **Steps inside the long-pole jobs**, the overlapped steps should take about as long as the slowest of them, and the job's p50 duration should fall by the rest.
- Runner minutes fall by the same amount, because the job finishes sooner.
- Break one overlapped command on a branch, for example with a wrong image tag, and confirm the job fails.

## Sources

- Materialize: [Materialize blog: provision test agents and pull images while the build is still running](https://materialize.com/blog/speeding-up-materialize-ci/). Preparation time fell from 4 minutes to 1 minute on average.
- OpenAI: [codex: compress the release binaries with two parallel workers](https://github.com/openai/codex/pull/27855). Three trials took 121 to 123 s serially and 73 to 74 s in parallel, saving 47 to 50 seconds in the x64 packaging lane.
- Stripe: [sync-engine-fork: pull the Docker images while dependencies install and build](https://github.com/stripe/sync-engine-fork/pull/223)
- Mastra: [mastra: run ESLint and Prettier concurrently in one Turbo invocation](https://github.com/mastra-ai/mastra/pull/18428)
