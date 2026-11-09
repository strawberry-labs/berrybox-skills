# Fetch only the history and files a job needs

Keep actions/checkout at its default single commit, give the few jobs that diff or version just the history they read, and use blobless or sparse checkouts for jobs that need commit history or a few folders but not every file.

- Playbook: [Get setup off the clock](https://berrybox.io/playbooks/slow-setup.md)
- Saves: wait time and runner minutes
- Risk: low
- Web page: https://berrybox.io/playbooks/slow-setup/shallow-checkout

## Signals in your baseline

- Checkout takes more than 10 to 15 seconds at p50 in the long-pole step table, or its p90 is several times its p50.
- Workflows set fetch-depth 0 in jobs that only build or test the current commit.
- Change-detection, labeling or other gate jobs check out the whole tree to read a diff or a few files.
- Checkouts set lfs true in jobs that never open the LFS files.

## Why it works

`actions/checkout` fetches a single commit unless you ask for more. Many workflows ask for everything with `fetch-depth: 0`, which downloads every commit, branch and tag, and every past version of every file. On a repository with a few years of history that is gigabytes, and it grows with every merge. Large transfers also make up the slow tail: one stalled fetch can hold the job for minutes.

Most jobs build and test the commit in front of them and need none of that. Jobs that do need history, to diff against the base branch or to compute a version from tags, usually need commits and trees, not the contents of old files. Git can fetch those separately. A blobless clone (`filter: blob:none`) downloads the commit graph and fetches file contents only when a command reads them. A sparse checkout writes only the folders you list.

## Apply it

List every checkout that asks for more than the default:

```sh
grep -rn -E "fetch-depth|filter:|sparse-checkout|lfs:" .github/workflows
```

Then give each job the lightest variant it can use.

### Build and test jobs

Delete `fetch-depth: 0` (the default is 1) and `lfs: true`, unless the job reads LFS files or runs a tool that needs history (see Keep it safe).

### Jobs that list a pull request's changed files

On `pull_request`, checkout gives you GitHub's merge commit. Its first parent is the tip of the base branch, so two levels of history are enough:

```yaml
- uses: actions/checkout@v7
  with:
    fetch-depth: 2
- name: List changed files
  run: |
    git diff --name-only HEAD^1 HEAD > changed-files.txt
    cat changed-files.txt
```

Write to the file directly rather than through a pipe. The default `run` shell doesn't set `pipefail`, so a failed `git diff | tee` would still pass with an empty list.

For `push` and `merge_group` events, fetch the one base commit you compare against (`github.event.before`, or `github.event.merge_group.base_sha`) with `git fetch --depth=1 origin <sha>`, then diff the two commits directly. A two-dot diff compares trees and needs no merge base.

### Jobs that walk history but don't read old files

Changelog, release-note and three-dot diff jobs keep full history but skip file contents:

```yaml
- uses: actions/checkout@v7
  with:
    fetch-depth: 0
    filter: blob:none
```

`git log`, `git merge-base` and `git diff --name-only base...head` work as before: a blobless clone keeps every commit and tree, and fetches file contents only when a command reads them.

### Gate jobs that read a few folders

```yaml
- uses: actions/checkout@v7
  with:
    sparse-checkout: |
      .github
      scripts/ci
```

Cone mode, the default, writes the listed folders plus the files at the repository root. If a job never reads the tree at all (it calls the API, posts a comment or applies labels), remove the checkout step.

## Keep it safe

- **Tools that read history.** `git describe`, Changesets, semantic-release, setuptools-scm, `nx affected` and any three-dot diff need commits or tags that a depth-1 clone lacks. Some fail loudly; others fall back to a default version or the wrong base. Search the job's commands before cutting its depth, and use `filter: blob:none` with full depth when in doubt.
- **Lazy fetches.** A blobless clone that later reads many old files fetches them on demand and can end up slower than a full clone. Keep a full clone for jobs that compare file contents across commits, not just names.
- **Change detection must fail toward running.** If the base commit is missing (a force push, a new branch where `before` is all zeros), treat everything as changed. A gate that silently reports "nothing changed" skips the downstream jobs, and a job skipped by an `if` condition reports as skipped, which satisfies a required check. Tests stop running and nothing turns red.
- **LFS.** With `lfs: false`, tests that read LFS fixtures get small pointer files instead. Keep `lfs: true` on those jobs only.
- **Security.** This play changes how much you fetch, not which ref. In `pull_request_target` and `workflow_run` workflows, keep checking out the base branch; checkout v7 refuses fork pull request code there unless you set `allow-unsafe-pr-checkout`.

## Verify

- Compare the checkout step's p50 and p90 with the [baseline](https://berrybox.io/playbooks/baseline.md). The p90 often moves more than the median.
- The checkout log prints the `git fetch` command; confirm it shows `--depth=1` or `--filter=blob:none` where you expect.
- For change-detection jobs, compare the listed files with `gh pr diff --name-only` on a few pull requests, and confirm the same downstream jobs run.
- Confirm the same number of tests ran and the same checks reported.

## Sources

- Linear: [Linear blog: cap fetch depth in change-detection gates and drop checkout from jobs that need no tree](https://linear.app/now/ci-bottleneck-reworked#fetch-only-what-each-job-needs). The slowest change-detection gate went from 94 seconds to 20 after capping fetch depth, and jobs that lost their checkout went from 27 seconds to 7.
- Sorbet: [sorbet: use a sparse checkout for the CI step that reports whether all jobs passed](https://github.com/sorbet/sorbet/pull/10214)
- OpenAI: [frontier-evals: fetch only the latest commit and skip LFS files in lint jobs](https://github.com/openai/frontier-evals/pull/53)
