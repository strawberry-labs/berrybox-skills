# Remove caches that take longer than the work they skip

Time each cache's restore and save against the work it skips, delete the ones that lose, save from the default branch only, and keep pull request and merge queue writes from evicting the entries main relies on.

- Playbook: [Get setup off the clock](https://berrybox.io/playbooks/slow-setup.md)
- Saves: wait time and runner minutes
- Risk: low
- Web page: https://berrybox.io/playbooks/slow-setup/drop-slow-caches

## Signals in your baseline

- A cache restore step or a Post step that saves a cache takes 20 seconds or more, or longer than the install or build it skips.
- Logs show "Cache not found" followed by a new save on most runs, so the cache rarely hits.
- gh cache list shows total usage near the repository limit, with many entries on pull request or merge queue refs.
- Release, tag or merge queue runs save caches that no later run can restore.

## Why it works

Every cache costs time on each run: a restore at the start and, whenever the exact key missed, a save in the job's post step. It pays off only when the work it skips takes longer. Caches go bad in a few predictable ways:

- The key changes on almost every run (it includes the commit SHA or a lockfile that changes daily), so nothing hits and every run uploads.
- The archive grows until restoring it takes longer than rebuilding.
- Runs save entries that nothing can restore. Each tag is its own cache scope, and merge queue runs write to temporary `gh-readonly-queue` refs.
- Pull request and queue writes fill the repository's quota, and GitHub evicts the least recently used entries, sometimes ones main relies on.

The save happens before the job can finish, so on a long-pole job its cost lands on the critical path.

## Apply it

### Measure each cache

```sh
gh api repos/{owner}/{repo}/actions/cache/usage
gh cache list --sort size_in_bytes --limit 30 --json key,ref,sizeInBytes,lastAccessedAt
```

The first command shows total usage; the second shows the biggest entries and which refs own them. Then take each cache step from the [baseline](https://berrybox.io/playbooks/baseline.md) step table: restore time, plus the matching `Post` step's save time. Compare that sum with a run where the cache missed. If restore plus save is close to the cold time, the cache isn't worth it.

### Remove or shrink the losers

- Delete caches that lose to a fresh install or build. Linear found its `node_modules` cache slower than a filtered install.
- Stop saving where nothing can restore. A tag run saves into a scope no other tag can read, and merge queue runs save to refs that disappear. Make those runs restore-only, or drop the cache when restores rarely help: OpenAI removed it from its Rust release builds after measuring uploads of about 230 seconds a run against downloads of about 5.
- Shrink caches that grew: prune stale entries before saving, and keep only what the current build uses. openai-java now saves only the current build's outputs.

### Save from one place

Restore everywhere, and save only on pushes to the default branch:

```yaml
- uses: actions/cache/restore@v6
  id: npm-cache
  with:
    path: ~/.npm
    key: ${{ runner.os }}-npm-${{ hashFiles('**/package-lock.json') }}
    restore-keys: |
      ${{ runner.os }}-npm-
- run: npm ci
- if: github.event_name == 'push' && github.ref == 'refs/heads/main' && steps.npm-cache.outputs.cache-hit != 'true'
  uses: actions/cache/save@v6
  with:
    path: ~/.npm
    key: ${{ steps.npm-cache.outputs.cache-primary-key }}
```

- `cache-primary-key` is the key the restore step computed, so the save uses the same one.
- `cache-hit` is true only on an exact match, so main saves once per lockfile change.
- Setup actions have their own switches: `save-if` in `Swatinem/rust-cache`, `save-cache` in `astral-sh/setup-uv`, and `cache-read-only` in `gradle/actions/setup-gradle`, which is already on outside the default branch.

### Clean up closed pull requests

Pull request caches expire after 7 days unused, but on a busy repository they can crowd out main's entries first. This workflow deletes a pull request's caches when it closes:

```yaml
name: Clean closed PR caches
on:
  pull_request_target:
    types: [closed]

permissions: {}

jobs:
  clean:
    runs-on: ubuntu-latest
    permissions:
      actions: write
    steps:
      - env:
          GH_TOKEN: ${{ github.token }}
          PR_NUMBER: ${{ github.event.pull_request.number }}
        run: gh cache delete --all --ref "refs/pull/$PR_NUMBER/merge" --succeed-on-no-caches --repo "$GITHUB_REPOSITORY"
```

It uses `pull_request_target` so the token can delete caches for fork pull requests too. It never checks out or runs pull request code, and its only input is the pull request number.

## Keep it safe

- **Correctness.** Removing a cache should change timing, never results. If a test fails once a cache is gone, the cache was hiding a missing install or build step; fix the step.
- **Trade-offs of save-on-main.** A pull request that changes the lockfile restores an older entry and downloads the difference on every push. Anthropic accepted the same trade in buffa, where a pull request that edits the cached Dockerfile rebuilds cold on every push, because such pull requests are rare. The first main run after a lockfile change is also cold.
- **Security.** Keep low-trust workflows read-only: don't declare `cache-mode: write` on `pull_request_target`, `issue_comment` or `workflow_run`. Keep the cleanup workflow as it is, with no checkout and only `actions: write`.
- **Required checks.** If you move a cache save into its own job, give it a name no branch protection rule requires, and don't make required jobs `needs` it.

## Verify

- In the long-pole step table, the restore and `Post` save steps should be gone or shorter, and the job's p50 and p90 should not rise. If a job gets slower without its cache, put the cache back.
- After a week, rerun `gh cache list`: entries should sit mostly on `refs/heads/main`, and total usage should stay under the limit.
- Confirm the same number of tests ran and the same checks reported.

## Sources

- OpenAI: [codex: remove actions/cache from the Rust release workflows](https://github.com/openai/codex/pull/11540). Across 289 release-tag runs, cache download averaged about 5 seconds per run while cache upload averaged about 230 seconds on alpha tags and 227 on stable tags.
- Linear: [Linear blog: drop the node_modules cache in favor of a filtered install](https://linear.app/now/ci-bottleneck-reworked#don%27t-cache-when-it%27s-faster-to-rebuild). Even a cache hit took about 28 seconds to restore, compared with roughly 7.5 seconds for a filtered install.
- OpenAI: [openai-java: save only the current build's Gradle cache entries instead of the full history](https://github.com/openai/openai-java/pull/1203). Cache archives had reached 3.1 GB and took 30 to 70 seconds to restore; the compact snapshot held 32 entries in 118 MiB.
- Anthropic: [buffa: write the Docker build cache only from pushes to main, and make pull request and queue runs restore-only](https://github.com/anthropics/buffa/pull/288)
