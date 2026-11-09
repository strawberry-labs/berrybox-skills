# Catch lint, format and type errors before they reach CI

Run the repository's fast checks in a pre-push hook so lint, format and type failures cost seconds on the author's machine instead of a CI run, and keep the same checks in CI for pushes that skip the hook.

- Playbook: [Keep CI ahead of a growing pull request queue](https://berrybox.io/playbooks/pr-volume.md)
- Saves: wait time and runner minutes
- Risk: low
- Web page: https://berrybox.io/playbooks/pr-volume/check-before-push

## Signals in your baseline

- Many recent failed pull_request runs failed first in a lint, format or type-check step.
- Pull requests carry follow-up commits such as "fix lint" or "format", each starting a full run.
- The repository has no hook configuration (lefthook.yml, .pre-commit-config.yaml, .husky/), or agents push from environments where a global core.hooksPath hides the repository's hooks.

## Why it works

A lint failure found in CI costs a full round trip: push, wait for a runner, install and build, read the log, fix one line, push again and start another full run. The same check on the author's machine takes seconds. Coding agents make the round trip more common, because they push often and fix whatever CI reports. Stripe's coding agents run a lint step in a local loop before they push. For its engineers, a background service caches lint results, so the hooks that run on push usually correct frequent lint problems in well under a second.

Pre-push is usually the right moment. A pre-commit hook runs on every commit, and agents commit constantly: cmux chose pre-push for web checks that take 3 to 10 seconds for that reason. CI still runs the same checks. The hook moves the first failure earlier; it doesn't replace the gate.

## Apply it

### lefthook (Node, Go, Rust and mixed repositories)

```yaml
# lefthook.yml
pre-push:
  parallel: true
  jobs:
    - name: lint
      run: pnpm lint
    - name: format
      run: pnpm exec prettier --check .
    - name: typecheck
      run: pnpm exec tsc --noEmit
```

- Install it with `pnpm add -D lefthook` and add `"prepare": "lefthook install"` to the `package.json` scripts, so every clone gets the hook on install.
- lefthook is a single binary, so the same file works for other languages: `test -z "$(gofmt -l .)"` and `go vet ./...` for Go, `cargo fmt --check` for Rust. Add `cargo clippy` only if it finishes in seconds on a warm build.
- For a slow linter, `{push_files}` in `run` passes only the files changed in the commits being pushed.

### pre-commit (Python)

```yaml
# .pre-commit-config.yaml
default_install_hook_types: [pre-push]
default_stages: [pre-push]
repos:
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.17.4
    hooks:
      - id: ruff-check
      - id: ruff-format
```

- `default_install_hook_types` makes `pre-commit install` set up the pre-push hook, and `default_stages` runs these hooks at push time. When a hook rewrites files, the push fails: commit the changes and push again.
- In CI, `pre-commit run --all-files` alone runs only commit-stage hooks and would skip these. Add the stage:

```yaml
  lint:
    runs-on: ubuntu-latest
    timeout-minutes: 10
    steps:
      - uses: actions/checkout@v7
      - uses: actions/setup-python@v7
        with:
          python-version: "3.13"
      - run: pip install pre-commit==4.7.0
      - run: pre-commit run --all-files --hook-stage pre-push --show-diff-on-failure
```

### Coding agents

- Name the command in `AGENTS.md` (and `CLAUDE.md` for Claude Code), and say the hook enforces it, as cmux did.
- Make sure hooks run where the agent works. Sentry's agent set a global `core.hooksPath` for its own commit hook, which hid the repository's `.git/hooks`. The repository's lint hooks never ran, and CI failed on a stale file they would have caught. Run `git config --show-origin --get-all core.hooksPath` in the agent's environment: a global or system value means hooks in `.git/hooks` are skipped.

## Keep it safe

- Hooks are optional. `git push --no-verify` skips them, and a fresh clone has none until they're installed. Keep the same checks as a fast required job in CI. cmux added a CI job that runs the hook's script on the pushed range, so a skipped hook shows red within minutes.
- Most hooks check the working tree, not the commit being pushed. Uncommitted edits can let a bad commit through or block a good one, and `git push origin other-branch` checks whatever is checked out, not `other-branch`. Push from a clean tree, or have the hook check out the pushed commit, as cmux's hook now does in a temporary worktree.
- Keep the hook to seconds, or people and agents will skip it. Slow tests belong in CI or in an agent's [checks before it opens a pull request](https://berrybox.io/playbooks/pr-volume/verify-before-pr.md).
- Pin tool versions (`rev` for pre-commit, the lockfile for Node tools) so the hook and CI give the same answer.

## Verify

- Commit a deliberate lint error and push. The push should be refused within seconds, naming the error.
- Push the same commit with `--no-verify` to a scratch branch and open a draft pull request. CI's lint job should fail. Close the pull request and delete the branch.
- After two weeks, count failed `pull_request` runs whose first failing step is lint, format or type checking, and compare with the [baseline](https://berrybox.io/playbooks/baseline.md) period. The count should drop, and so should `pull_request` runs per merged pull request.

## Sources

- Stripe: [Stripe Dev blog: fix common lint issues in pre-push hooks and have coding agents loop on lint locally before pushing](https://stripe.dev/blog/minions-stripes-one-shot-end-to-end-coding-agents-part-2)
- Manaflow: [cmux: add a web lint pre-push hook for agent pushes, with a fast CI job that catches skipped hooks](https://github.com/manaflow-ai/cmux/commit/0b115ab19af7450bc9e95e68c9fe096cd7d07a50)
- Manaflow: [cmux: make the pre-push hook lint the pushed commit instead of the working tree](https://github.com/manaflow-ai/cmux/pull/23082)
- Sentry: [junior: run repository Git hooks in agent sandboxes after a global hooks path hid them](https://github.com/getsentry/junior/pull/2446)
