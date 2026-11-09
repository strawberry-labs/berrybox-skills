# Pin service images and tools to exact versions

Replace floating tags such as latest in services, containers, runner labels and tool installs with exact versions or digests, so a run changes only when a commit changes it, and take updates through reviewed pull requests.

- Playbook: [Make a red build mean something broke](https://berrybox.io/playbooks/flaky-tests.md)
- Saves: wait time and runner minutes
- Risk: low
- Web page: https://berrybox.io/playbooks/flaky-tests/pin-service-images

## Signals in your baseline

- Workflow services, container images or Compose files use latest, a major-only tag such as postgres:18, or no tag at all.
- Tools install at whatever version is newest (brew upgrade, version latest, pip install without a version, a releases/latest download URL).
- Several unrelated pull requests started failing on the same day with no related change on the default branch.
- Jobs run on ubuntu-latest, windows-latest or macos-latest and broke when the label moved to a newer image.

## Why it works

A floating tag is a pointer that someone else moves. When `localstack/localstack:latest` or `postgres:latest` points at a new release, every run picks it up that day, whatever its commit changed. The failure looks like a flake, except that a rerun doesn't help and older commits fail too. Quickwit's coverage job failed every run for a month while it pulled LocalStack's `latest`, which had started requiring an auth token. Runner labels move the same way: GitHub is moving `ubuntu-latest` from Ubuntu 24.04 to 26.04 in a rollout between October 19 and November 19, 2026, so during those weeks a job on that label may get either image.

Pinning makes the environment part of the commit. An upgrade arrives as its own pull request, and if it breaks something, the cause is obvious. A version tag can still be republished (Rundeck saw this with `ubuntu:22.04`), so pin images by tag and digest: the tag tells people what the image is, and the digest makes it immutable and guards against a hijacked tag.

## Apply it

### Find floating references

```bash
git grep -nE '(image|container):[[:space:]]+[^@[:space:]]+[[:space:]]*$' -- .github '*compose*.y*ml'
git grep -nE 'runs-on:.*-latest|version: *latest|brew upgrade|releases/latest' -- .github
```

The first command lists image references without a digest; the second, runner labels and tool installs that follow the newest release.

### Pin services and containers

```yaml
jobs:
  integration:
    runs-on: ubuntu-24.04
    timeout-minutes: 20
    services:
      postgres:
        image: postgres:18.6@sha256:e3d24f6906d0760bf4da0dae872415391ededefad23fd471c47dc53b0ddf3c42
        env:
          POSTGRES_PASSWORD: postgres
        ports:
          - 5432:5432
        options: >-
          --health-cmd "pg_isready -h 127.0.0.1 -U postgres"
          --health-interval 2s
          --health-timeout 5s
          --health-retries 30
    steps:
      - uses: actions/checkout@v7
      - run: ./scripts/integration-tests.sh
        env:
          DATABASE_URL: postgres://postgres:postgres@localhost:5432/postgres
```

- `ubuntu-24.04` names the runner image instead of following `ubuntu-latest`. Move to 26.04 in a pull request of its own.
- The digest is the multi-platform index digest, shown by `docker buildx imagetools inspect postgres:18.6`, so the same pin works on x64 and Arm runners. Restate pins its LocalStack service the same way, with a dated tag plus digest.
- Pin the version you run in production. If you support several, test a matrix of pinned versions instead of `latest`.
- The health check connects over TCP, as the tests do. See [wait for readiness](https://berrybox.io/playbooks/slow-tests/poll-dont-sleep.md).

### Pin tools

- Read versions from files in the repository: `go-version-file: go.mod`, `node-version-file: .nvmrc`, `python-version-file: .python-version`, the `packageManager` field for pnpm or Yarn, and `rust-toolchain.toml` for Rust.
- Give actions that install a linter or CLI an exact `version` instead of `latest`.
- Download binaries by an exact release and check the checksum, as Stripe now does for `xcodes` instead of running `brew upgrade` on every worker:

```bash
curl --fail --location --silent --show-error --retry 3 --output actionlint.tar.gz \
  https://github.com/rhysd/actionlint/releases/download/v1.7.12/actionlint_1.7.12_linux_amd64.tar.gz
echo "8aca8db96f1b94770f1b0d72b6dddcb1ebb8123cb3712530b08cc387b349a3d8  actionlint.tar.gz" | sha256sum --check
tar -xzf actionlint.tar.gz
```

### Keep the pins current

A pin without updates goes stale and stops receiving security fixes; Quickwit notes that its pinned LocalStack will get no more patches. Renovate's GitHub Actions manager reads `services:` and `container:` images, and its `pinDigests` option adds and refreshes digests. Rundeck groups updates to CI-only images into one weekly pull request that a person reviews, and keeps major versions behind an approval.

## Keep it safe

- **Required checks.** Changing a tag or a `runs-on` label keeps check names, unless the value appears in the job name, as in a matrix job called `test (18)` or `test (ubuntu-latest)`. Update branch protection in the same change if it does.
- **Security.** Only a digest protects against a re-pointed or hijacked tag. Don't automerge image updates in workflows that hold secrets. Fork pull requests get no secrets, so they can't use registry `credentials` stored in secrets; prefer images that allow anonymous pulls, or a mirror.
- **Day-one behavior.** Pin to what the floating tag resolves to today, as Rundeck did, so nothing changes until an update pull request says so. Don't pin to an older version just because it passes.
- **Stale pins.** Watch that update pull requests keep merging. A pin nobody bumps is a security risk, not a fix.

## Verify

- Rerun the two `git grep` commands. No image without a digest, and no `-latest` label you meant to pin, should remain.
- After two weeks, rerun the [baseline](https://berrybox.io/playbooks/baseline.md). Failed first attempts in "Initialize containers" and setup steps should drop, and the Reruns column should hold or fall.
- The "Initialize containers" step should take about as long as before.
- The same tests should run, and every required check should report under its old name.

## Sources

- Quickwit: [quickwit: pin the coverage workflow's LocalStack service from latest to 4.14.0 after latest began requiring an auth token](https://github.com/quickwit-oss/quickwit/pull/6303). Coverage CI had a 100% failure rate for the month before this change, while the job pulled localstack/localstack:latest.
- Restate: [restate sdk-typescript: pin the LocalStack service in the Lambda test workflow to a dated tag plus digest](https://github.com/restatedev/sdk-typescript/pull/823)
- Rundeck: [rundeck: pin every external CI and test image by tag plus digest, with grouped weekly Renovate updates that a person reviews](https://github.com/rundeck/rundeck/pull/10676)
- Stripe: [stripe-ios: install a pinned, checksum-verified xcodes release instead of upgrading it with Homebrew on every worker](https://github.com/stripe/stripe-ios/pull/7331)
