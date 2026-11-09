# Build once and pass the output to the jobs that need it

Compile, bundle or build the image in one job, upload the result as an artifact, and have test shards, end-to-end jobs and packaging download it instead of repeating the same build on every runner.

- Playbook: [Shorten the path that ends the run](https://berrybox.io/playbooks/critical-path.md)
- Saves: wait time and runner minutes
- Risk: medium
- Web page: https://berrybox.io/playbooks/critical-path/build-once

## Signals in your baseline

- Several jobs or matrix legs in one workflow run the same build command, such as npm run build, cargo build, go build or docker build, before their own work.
- In "Steps inside the long-pole jobs", a build or compile step takes a large share of a test job.
- A packaging or deploy job rebuilds what an earlier job in the same run already built and tested.

## Why it works

Jobs don't share a disk. If four test shards, an end-to-end job and a packaging job each run `cargo build` or `npm run build`, the run pays for the same compile six times, and each of those jobs carries the build on its way to the finish. Build once, upload the output with `actions/upload-artifact`, and let each consumer download it. Downloading a few hundred megabytes takes seconds, while compiling usually takes minutes. You also test the exact files you package, rather than a second build that is supposed to match.

The cost is a new wait: consumers start after the build job instead of building side by side. That trade pays off when the consumers would all have run the same build anyway, which is the usual case for test shards and end-to-end jobs.

## Apply it

### Node (npm or pnpm)

Build the app once and run the end-to-end suite against it on four shards:

```yaml
jobs:
  build:
    runs-on: ubuntu-24.04
    steps:
      - uses: actions/checkout@v7
      - uses: actions/setup-node@v7
        with:
          node-version: 24
          cache: npm
      - run: npm ci
      - run: npm run build
      - uses: actions/upload-artifact@v7
        with:
          name: web-dist
          path: dist/
          if-no-files-found: error
          retention-days: 3

  e2e:
    needs: build
    runs-on: ubuntu-24.04
    strategy:
      fail-fast: false
      matrix:
        shard: [1, 2, 3, 4]
    steps:
      - uses: actions/checkout@v7
      - uses: actions/setup-node@v7
        with:
          node-version: 24
          cache: npm
      - run: npm ci
      - uses: actions/download-artifact@v8
        with:
          name: web-dist
          path: dist/
      - run: npx playwright install --with-deps chromium
      - run: npx playwright test --shard=${{ matrix.shard }}/4
```

- `if-no-files-found: error` fails the build job when the path is wrong, instead of letting the shards test an empty directory.
- `retention-days: 3` keeps the artifact long enough to rerun a failed shard, which downloads the artifact the first attempt uploaded.
- The shards still run `npm ci` for the test tools, but nothing should rebuild `dist/`. Check that Playwright's `webServer.command` serves the downloaded files instead of running the build again.

### Rust

`cargo nextest archive` packs the compiled test binaries into one file that other jobs can run without compiling:

```yaml
jobs:
  build-tests:
    runs-on: ubuntu-24.04
    steps:
      - uses: actions/checkout@v7
      - uses: dtolnay/rust-toolchain@stable
      - uses: taiki-e/install-action@nextest
      - run: cargo nextest archive --workspace --archive-file nextest.tar.zst
      - uses: actions/upload-artifact@v7
        with:
          name: nextest-archive
          path: nextest.tar.zst
          retention-days: 3

  test:
    needs: build-tests
    runs-on: ubuntu-24.04
    strategy:
      fail-fast: false
      matrix:
        partition: [1, 2, 3, 4]
    steps:
      - uses: actions/checkout@v7
      - uses: taiki-e/install-action@nextest
      - uses: actions/download-artifact@v8
        with:
          name: nextest-archive
      - run: >-
          cargo-nextest nextest run
          --archive-file nextest.tar.zst
          --workspace-remap ${{ github.workspace }}
          --partition slice:${{ matrix.partition }}/4
```

- The archive holds test binaries, not source. The test job checks out the same commit so tests that read fixture files find them, and `--workspace-remap` points the binaries at that checkout.
- `--partition slice:N/4` gives each job a quarter of the tests.

### Docker

Build the image once and load it in each job that tests it:

```yaml
jobs:
  image:
    runs-on: ubuntu-24.04
    steps:
      - uses: actions/checkout@v7
      - uses: docker/setup-buildx-action@v4
      - uses: docker/build-push-action@v7
        with:
          context: .
          tags: app:ci
          outputs: type=docker,dest=${{ runner.temp }}/app.tar
      - uses: actions/upload-artifact@v7
        with:
          name: app-image
          path: ${{ runner.temp }}/app.tar
          retention-days: 1

  integration:
    needs: image
    runs-on: ubuntu-24.04
    steps:
      - uses: actions/download-artifact@v8
        with:
          name: app-image
          path: ${{ runner.temp }}
      - run: docker load --input ${{ runner.temp }}/app.tar
      - run: docker run --rm app:ci npm test
```

- `outputs: type=docker,dest=...` writes the image to a tarball instead of pushing it, and `docker load` restores it under the `app:ci` tag.

## Keep it safe

- Run the build and its consumers on the same runner label, such as `ubuntu-24.04`. `ubuntu-latest` moves to new Ubuntu releases, and a binary linked against a newer C library or built for a newer CPU baseline may not run on an older image.
- Make sure consumers use the artifact. A test command that rebuilds, such as an npm pre-script, a Playwright `webServer` that runs the build, or `cargo nextest run` without `--archive-file`, pays twice and tests something else.
- `upload-artifact` doesn't keep file permissions. Pack executables into a tarball first, as the nextest archive and the image already are, or `chmod +x` them after download.
- Never upload secrets. Anyone who can read the repository can download its artifacts, so keep `.env` files, `.npmrc` tokens and credentials out of the uploaded paths.
- Treat artifacts from fork pull requests as untrusted. Using them inside the same `pull_request` run is fine. Downloading them into a `workflow_run` or `pull_request_target` workflow that holds secrets can hand those secrets to the fork's code.
- Artifact names must be unique within a run. If matrix legs each upload, put the leg in the name, such as `dist-${{ matrix.os }}`.
- Shard jobs report as checks named `e2e (1)`, `e2e (2)` and so on, and those names change when the shard count does. Require an aggregate job instead, as in [parallelize independent jobs](https://berrybox.io/playbooks/critical-path/parallelize-independent-jobs.md).

## Verify

- In the branch baseline, the build step should disappear from every consumer job, and **Runner min/run (p50)** should fall by about one build per consumer.
- Wall time can move either way, because consumers start later but finish sooner. Compare p50 wall for the workflow, and check that the build job hasn't become the new **Long-pole job**.
- Confirm that the same number of tests ran, using the counts in the job logs or JUnit reports, and that every shard downloaded the artifact.

## Sources

- OpenAI: [codex: build one nextest archive per platform and run it across four test shards](https://github.com/openai/codex/pull/23358)
- Spotify: [confidence-resolver: base the Docker test and lint stages on the build stage instead of compiling again](https://github.com/spotify/confidence-resolver/pull/355). In a no-cache benchmark, total compute across the affected stages fell 61%, from 1807 s to 712 s.
- Stripe: [stripe-react-native: build the app once and have the sharded test runners download it](https://github.com/stripe/stripe-react-native/pull/2137)
- OpenAI: [codex-security: rely on the existing prepack build instead of building the package again in CI](https://github.com/openai/codex-security/pull/397)
