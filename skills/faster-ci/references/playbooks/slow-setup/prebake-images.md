# Bake stable dependencies into the runner or container image

Move the tools and system packages that every job installs and that rarely change into a prebuilt container or runner image, rebuilt on a schedule and whenever its inputs change.

- Playbook: [Get setup off the clock](https://berrybox.io/playbooks/slow-setup.md)
- Saves: wait time and runner minutes
- Risk: medium
- Web page: https://berrybox.io/playbooks/slow-setup/prebake-images

## Signals in your baseline

- Several jobs run the same apt-get, brew or curl installs of compilers, database clients or CLIs on every run.
- Steps before the first real command take a minute or more in most jobs, even with dependency caches hitting.
- Reruns trace back to toolchain or header downloads that hung or failed during setup.
- The same block of setup steps is copied across many workflows and matrix entries.

## Why it works

A dependency cache still pays to download and unpack on every job, and an `apt-get install` or `curl | sh` pays a network round trip, package resolution and install time on top. When the same tools appear in every job and change less often than weekly, install them once into an image. Every job then starts with them on disk, and a slow mirror can only break the image build, not your pull requests.

You trade per-run setup for a pipeline that keeps the image current. There are two places to bake:

- A **container image** that the job runs in (`container:`), which works on any Linux runner, GitHub-hosted included.
- The **runner's VM image**: custom images on GitHub larger runners, Packer-built machine images for self-hosted fleets, or a custom runner image for Actions Runner Controller.

## Apply it

1. List what each job installs before its first real command: setup actions for toolchains, `apt-get`, `curl` downloads, globally installed CLIs. Keep only stable items for the image; project dependencies that follow the lockfile stay in a [dependency cache](https://berrybox.io/playbooks/slow-setup/cache-dependencies.md).
2. Write them into a Dockerfile (or image script) with every version pinned.
3. Build the image from the default branch only: on a push that changes it, weekly for security updates, and on demand.

```yaml
name: CI image
on:
  push:
    branches: [main]
    paths: ["ci/**"]
  schedule:
    - cron: "0 5 * * 1"
  workflow_dispatch:

permissions:
  contents: read
  packages: write

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7
      - name: Build and push
        env:
          REGISTRY_TOKEN: ${{ github.token }}
        run: |
          image="ghcr.io/$(echo "$GITHUB_REPOSITORY" | tr '[:upper:]' '[:lower:]')/ci"
          echo "$REGISTRY_TOKEN" | docker login ghcr.io -u "$GITHUB_ACTOR" --password-stdin
          docker build -f ci/Dockerfile -t "$image:$GITHUB_SHA" ci
          docker push "$image:$GITHUB_SHA"
```

- `packages: write` lives only in this workflow. Jobs that pull the image need `packages: read`.
- The registry path must be lowercase, which `tr` handles for organization names with capitals.
- Each build gets its own tag. Consumers point at an explicit tag, so a new image reaches CI through a pull request that bumps the tag and runs the whole suite on it.

Then use it in the job:

```yaml
jobs:
  test:
    runs-on: ubuntu-latest
    permissions:
      contents: read
      packages: read
    container:
      image: ghcr.io/acme/app/ci:4f6d2c1e9b0a7d3f5c8e1b2a6d9f0c3e7a5b8d1f
      credentials:
        username: ${{ github.actor }}
        password: ${{ github.token }}
    steps:
      - uses: actions/checkout@v7
      - run: make test
```

Include `git` in the image. Without it, `actions/checkout` falls back to downloading a tarball with no Git history.

On GitHub larger runners, the same idea works at the VM level: a job with the `snapshot` keyword on an image-generation runner saves the machine as a new custom image version when it succeeds, and a runner created from that image starts with everything installed. See GitHub's guide to [custom images](https://docs.github.com/en/actions/how-tos/manage-runners/larger-runners/use-custom-images).

## Keep it safe

- **Treat the image as a head start, not a requirement.** Keep the job's own install commands where you can, so they find most of the work done: VS Code's jobs run their normal pnpm install on top of the image, which installs only what changed. Bun keys its baked downloads by content, so a version bump misses that one entry and downloads it, with no image rebuild. A stale image then costs time instead of producing a wrong result.
- **Pin and check versions.** The image's versions now live outside the repository's lockfiles. Pin them in the Dockerfile, and have the job print or assert the versions it depends on.
- **Build from trusted refs only.** Every job trusts the image. Use only images built from the default branch, as VS Code does, and keep secrets out of them: anyone who can pull an image can read its layers. With GitHub custom images, anyone with write access can generate an image from any branch, so keep image-generation runners in a dedicated runner group and limit the `snapshot` job to the default branch with its `if:` condition.
- **Watch the pull.** A 5 GB image can take longer to pull than the installs it replaced. Keep it small and measure the `Initialize containers` step.
- **Required checks.** Moving a job into a container doesn't rename it. A bad image breaks every job at once, which explicit tags let you roll back with one revert.

## Verify

- Compare time-to-first-real-command per job with the [baseline](https://berrybox.io/playbooks/baseline.md): the removed install steps should be gone, and the image pull or VM boot shouldn't eat the gain.
- Over a week, reruns caused by setup downloads should drop.
- Confirm the job logs the tool versions you expect, the same tests ran, and the same checks reported.

## Sources

- GitHub: [GitHub blog: run GitHub.com's CI on larger runners booted from custom images with tools and source preinstalled](https://github.blog/engineering/how-github-uses-github-actions-and-actions-larger-runners-to-build-and-test-github-com/). Without custom images, our workflows would take around 50 minutes from start to finish, versus the 12 minutes they take today.
- Linear: [Linear blog: move the Postgres client and native build headers into a small CI base image](https://linear.app/now/ci-bottleneck-reworked#preinstall-shared-dependencies-in-the-ci-image). Each API test shard had spent 7 to 8 seconds per run installing the same Postgres client with apt.
- Bun: [bun: bake a content-addressed download cache of build dependencies into the CI images](https://github.com/oven-sh/bun/pull/29568)
- Microsoft: [vscode: build disk images of a ready main workspace daily and when install inputs change](https://github.com/microsoft/vscode/pull/346211)
