# Reuse Docker layers across runners

Export BuildKit's layer cache to the GitHub Actions cache or a registry, and order the Dockerfile so a source change rebuilds only the layers that come after it.

- Playbook: [Build less, and build it faster](https://berrybox.io/playbooks/slow-builds.md)
- Saves: wait time and runner minutes
- Risk: low
- Web page: https://berrybox.io/playbooks/slow-builds/docker-layer-cache

## Signals in your baseline

- `docker/build-push-action` or `docker build` runs without `cache-from`, so every image build starts from an empty builder.
- Image build logs rerun the dependency install (`npm ci`, `go mod download`, a dependency `cargo build`) on every commit, with no `CACHED` lines, even when the lockfile didn't change.
- The Dockerfile runs `COPY . .` before installing dependencies, or declares a per-commit `ARG` such as the Git SHA above an expensive `RUN`.
- Two or more image jobs in the repository use `type=gha` without a `scope`, so each one overwrites the other's cache.

## Why it works

A hosted runner starts with an empty Docker builder, so every image build pulls the base image and runs every instruction again. BuildKit can export the cache for each layer to an outside store and import it on the next runner. A layer's cache key covers its instruction, the files it copies and every layer above it. When the key matches, BuildKit reuses the stored layer. The first instruction whose inputs changed, and everything below it, rebuilds.

Two things decide the hit rate: where the cache lives between runners, and the order of the Dockerfile. Put steps that rarely change (system packages, dependency installs) above steps that change on every commit (copying source, stamping a version).

## Apply it

### GitHub Actions cache backend

```yaml
name: image
on:
  pull_request:
  push:
    branches: [main]

permissions:
  contents: read
  packages: write

jobs:
  image:
    runs-on: ubuntu-latest
    timeout-minutes: 30
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
          push: ${{ github.event_name == 'push' }}
          tags: ghcr.io/acme/app:${{ github.sha }}
          build-args: GIT_SHA=${{ github.sha }}
          cache-from: type=gha,scope=app
          cache-to: ${{ github.event_name == 'push' && 'type=gha,scope=app,mode=max,ignore-error=true' || '' }}
```

- Pull requests build the image without pushing and read the layers that `main` saved. Only pushes to `main` log in, push and write the cache.
- `mode=max` exports the layers of every stage, including intermediate stages such as a dependency stage that never reaches the final image. The default, `mode=min`, keeps only the final image's layers, so a multi-stage build reruns its dependency install on each fresh runner. `max` costs more cache space.
- `scope` names the cache. Builds that share a scope overwrite each other's cache, and the default scope is `buildkit`, so give each image, and each architecture, its own.
- `ignore-error=true` keeps a failed cache export from failing the build.
- Replace `ghcr.io/acme/app` with your image. Registry paths must be lowercase.

### Registry backend

Use a registry when the cache outgrows the repository's Actions cache quota, or when builds outside Actions should share it. Point the cache at its own tag, never the tag you deploy:

```yaml
          cache-from: type=registry,ref=ghcr.io/acme/app:buildcache
          cache-to: ${{ github.event_name == 'push' && 'type=registry,ref=ghcr.io/acme/app:buildcache,mode=max,ignore-error=true' || '' }}
```

Reading a private cache image needs a login, so remove the `if:` from the login step. Pull request runs still never write.

### Dockerfile order

Copy the dependency manifests, install, and only then copy the source:

```dockerfile
# syntax=docker/dockerfile:1
FROM node:24-slim AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

FROM deps AS build
COPY . .
RUN npm run build

FROM node:24-slim
WORKDIR /app
ENV NODE_ENV=production
COPY package.json package-lock.json ./
RUN npm ci --omit=dev
COPY --from=build /app/dist ./dist
ARG GIT_SHA
LABEL org.opencontainers.image.revision=$GIT_SHA
CMD ["node", "dist/server.js"]
```

- A source-only change now reuses both `npm ci` layers and rebuilds from `COPY . .` down.
- Declare per-commit build args at the bottom. A new `ARG` value misses the cache at its first use, and every `RUN` after the declaration counts as a use. Sentry's revision `ARG` sat above its dependency build, which then reran for 3m41s to 3m54s in every image job.
- Add a `.dockerignore` listing `.git`, `node_modules`, `dist` and `coverage`, so `COPY . .` doesn't miss on files the image never uses.
- In Go, copy `go.mod` and `go.sum` and run `go mod download` before the source. In Rust, build dependencies from a `cargo chef` recipe first.
- Cache mounts (`RUN --mount=type=cache`) aren't part of the exported layer cache, so they start empty on a hosted runner. Put expensive downloads in ordinary layers.

## Keep it safe

- **Cache poisoning.** Write the cache only from trusted pushes. Never build pull request code in `pull_request_target` or `workflow_run` workflows: they run with the default branch's cache scope, and often a write token, so one pull request could plant layers that later `main` builds ship.
- **Stale packages.** A cached `RUN apt-get update && apt-get install` layer keeps the package versions it was built with until a line above it changes. Run a scheduled build with `no-cache: true`, or bump a base image pinned by digest, so security fixes land.
- **Secrets.** Never pass tokens through `build-args`: their values end up in image metadata. Use the action's `secrets` input with `RUN --mount=type=secret`, which keeps them out of every layer and the cache.
- **Cache quota.** A `mode=max` cache for a large image can take a big share of the repository's 10 GB and push out dependency caches, since GitHub evicts the least recently used entries over the limit. Check `gh cache list --sort size_in_bytes`, and move large images to the registry backend.
- **Required checks.** This play changes no job names or triggers, and pull requests still build the image, so the same checks report.

## Verify

- After one push to `main` writes the cache, open a pull request that changes one source file. The base image, manifest copy and `npm ci` steps should show `CACHED`, and only `COPY . .` onward should run.
- Compare the image job's p50 duration with the [baseline](https://berrybox.io/playbooks/baseline.md) over five or more runs. Report builds after a lockfile change separately; they rebuild the dependency layers.
- Run the same container smoke test or integration tests as before, and confirm the pushed tags and labels are unchanged.

## Sources

- Sentry: [taskbroker: move the per-commit revision ARG below the dependency build and give each architecture its own cache scope](https://github.com/getsentry/taskbroker/pull/817)
- PostHog: [duckgres: compile CGO dependencies and fetch extensions in layers keyed on go.sum, ahead of the source copy](https://github.com/PostHog/duckgres/pull/654)
- Stripe: [sync-engine-fork: add a registry layer cache to the arm64 image build so only the source copy rebuilds](https://github.com/stripe/sync-engine-fork/pull/223)
- Spotify: [confidence-resolver: build the deployer as a target of the shared Dockerfile and read the main branch's registry cache](https://github.com/spotify/confidence-resolver/pull/132)
