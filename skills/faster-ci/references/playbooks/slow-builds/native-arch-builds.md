# Build each architecture on a native runner instead of under QEMU

Build the amd64 and arm64 images in parallel on matching runners and merge them into one multi-arch tag, instead of compiling arm64 under QEMU on an x86 runner.

- Playbook: [Build less, and build it faster](https://berrybox.io/playbooks/slow-builds.md)
- Saves: wait time and runner minutes
- Risk: medium
- Web page: https://berrybox.io/playbooks/slow-builds/native-arch-builds

## Signals in your baseline

- An image workflow runs `docker/setup-qemu-action` and builds `platforms: linux/amd64,linux/arm64` on a single x86 runner.
- The multi-platform image job is the long pole of release or main-branch runs, and an amd64-only build of the same Dockerfile takes a fraction of its time.
- arm64 image builds crash or hang under emulation, for example `Illegal instruction` during a dependency install.

## Why it works

QEMU lets an x86 runner build an arm64 image by translating every arm64 instruction in software. Compilers and package installs run many times slower that way, and some tools crash outright. GitHub now hosts arm64 Linux runners (`ubuntu-24.04-arm` and `ubuntu-22.04-arm`) for public and private repositories. Build each architecture on a runner that matches it, run the two builds in parallel, then join the results into one multi-arch tag. The arm64 leg then runs at native speed, and the run takes about as long as the slower of the two legs.

## Apply it

### One job per architecture, then a merge job

```yaml
name: image
on:
  pull_request:
  push:
    branches: [main]

permissions:
  contents: read

env:
  IMAGE: ghcr.io/acme/app

jobs:
  build:
    strategy:
      matrix:
        include:
          - arch: amd64
            runner: ubuntu-24.04
          - arch: arm64
            runner: ubuntu-24.04-arm
    runs-on: ${{ matrix.runner }}
    timeout-minutes: 30
    permissions:
      contents: read
      packages: write
    steps:
      - uses: actions/checkout@v7
      - uses: docker/setup-buildx-action@f87e5991a6d7451dcb8d9637bfbc97413f497069 # v4.4.1
      - if: github.event_name == 'push'
        uses: docker/login-action@81c6f93d4bc991e510b342a00b419b3bb4efc5c6 # v4.7.0
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}
      - uses: docker/build-push-action@c3c9e263c25d99ce0380d002d59b67737d91b0dc # v7.4.0
        with:
          context: .
          platforms: linux/${{ matrix.arch }}
          push: ${{ github.event_name == 'push' }}
          tags: ${{ env.IMAGE }}:${{ github.sha }}-${{ matrix.arch }}
          cache-from: type=gha,scope=app-${{ matrix.arch }}
          cache-to: ${{ github.event_name == 'push' && format('type=gha,scope=app-{0},mode=max,ignore-error=true', matrix.arch) || '' }}

  merge:
    if: github.event_name == 'push'
    needs: build
    runs-on: ubuntu-24.04
    timeout-minutes: 10
    permissions:
      contents: read
      packages: write
    steps:
      - uses: docker/login-action@81c6f93d4bc991e510b342a00b419b3bb4efc5c6 # v4.7.0
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}
      - run: |
          docker buildx imagetools create -t "$IMAGE:$GITHUB_SHA" \
            "$IMAGE:$GITHUB_SHA-amd64" "$IMAGE:$GITHUB_SHA-arm64"
          docker buildx imagetools inspect "$IMAGE:$GITHUB_SHA"
```

- Each matrix leg builds one platform on a runner of that architecture, so no QEMU setup step is needed.
- Pull requests build both architectures without pushing, which catches arm64 breakage before merge. Only pushes to `main` log in, push and run the merge job.
- `imagetools create` writes a manifest list that points at the two per-architecture images. It copies no layers, so the merge job takes seconds.
- Each architecture gets its own cache scope. With a shared scope the two legs overwrite each other's cache, as Sentry found in its taskbroker image jobs.
- Replace `ghcr.io/acme/app` with your lowercase image name, and add your release tags to the `imagetools create` line.

To avoid the extra `-amd64` and `-arm64` tags, push by digest instead (`outputs: type=image,name=...,push-by-digest=true,name-canonical=true,push=true`), upload each digest as an artifact and merge `$IMAGE@sha256:...` references. Spotify's change uses that pattern. Docker's `docker/github-builder` reusable workflow also spreads a multi-platform build across native runners for you.

### Cross-compile instead

When the toolchain cross-compiles well (Go, Rust with a cross linker, plain JavaScript bundles), you can skip the second runner. Run the build stage on the runner's own platform and compile for the target:

```dockerfile
# syntax=docker/dockerfile:1
FROM --platform=$BUILDPLATFORM golang:1.27 AS build
ARG TARGETOS TARGETARCH
WORKDIR /src
COPY go.mod go.sum ./
RUN go mod download
COPY . .
RUN CGO_ENABLED=0 GOOS=$TARGETOS GOARCH=$TARGETARCH go build -o /out/app ./cmd/app

FROM gcr.io/distroless/static-debian13
COPY --from=build /out/app /app
ENTRYPOINT ["/app"]
```

One `build-push-action` call with `platforms: linux/amd64,linux/arm64` then needs no QEMU, because the final stage only copies files. Any `RUN` in the final stage would still run under emulation.

## Keep it safe

- **Required checks.** The matrix changes check names, for example from `build` to `build (arm64, ubuntu-24.04-arm)`. Update branch protection in the same change, or a required `build` check stays pending forever. The merge job reports `skipped` on pull requests, which still satisfies a requirement.
- **Partial publishes.** Consumers should pull only the merged tag. If one leg fails, the default `fail-fast: true` cancels the other and the merge job never runs, so no half-built multi-arch tag appears.
- **Runner size and queue.** In private repositories the arm64 standard runner has 2 vCPUs and 8 GB, half of what public repositories get. Compare its leg with the amd64 leg, and watch queue time on the arm64 label (see [cut queue time](https://berrybox.io/playbooks/runners/cut-queue-time.md)).
- **Permissions.** Only the jobs that push get `packages: write`, and pull request runs never log in. Fork pull requests get a read-only token either way.
- **Test what you ship.** A native arm64 runner can run the arm64 image. Add a smoke test there so the arm64 image gets the same check as amd64.

## Verify

- Compare the image workflow's wall-clock time with the [baseline](https://berrybox.io/playbooks/baseline.md). The arm64 leg should drop the most, and the run should take about as long as the slower leg plus a short merge job.
- Compare runner minutes too: two short native legs usually cost less than one long emulated job.
- Check the merged tag with `docker buildx imagetools inspect` and confirm it lists `linux/amd64` and `linux/arm64`, the same platforms the old image had.
- Confirm downstream deploys still pull the same tag names, and that the arm64 smoke test passes.

## Sources

- Spotify: [confidence-resolver: build the deployer image per architecture on native runners and merge the digests into one manifest](https://github.com/spotify/confidence-resolver/pull/479). In a test run of the same workflow, the build and manifest merge took about 17 minutes, down from 2 hours 28 minutes under QEMU.
- Stripe: [sync-engine-fork: replace the QEMU buildx run with parallel amd64 and arm64 jobs and a manifest job](https://github.com/stripe/sync-engine-fork/pull/212)
- Sentry: [action-release: build arm64 images on native runners after Node crashed under QEMU, and merge per-architecture tags](https://github.com/getsentry/action-release/pull/337)
