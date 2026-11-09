# Have coding agents run the checks before they open a pull request

Give agents one command that runs what CI requires, make them pass it before opening or updating a pull request, and cap CI rounds, so agent pull requests arrive green instead of using CI as a test runner.

- Playbook: [Keep CI ahead of a growing pull request queue](https://berrybox.io/playbooks/pr-volume.md)
- Saves: wait time and runner minutes
- Risk: low
- Web page: https://berrybox.io/playbooks/pr-volume/verify-before-pr

## Signals in your baseline

- Pull requests opened by agents fail their first CI run more often than those opened by people.
- AGENTS.md or CLAUDE.md doesn't name the commands that must pass before a pull request opens, or names commands that differ from what CI runs.
- Agent pull requests collect many fix-up pushes, each starting a full CI run.

## Why it works

An agent that opens a pull request and waits for CI to say what's wrong is using CI as its test runner. Each attempt costs a full run, a queue slot and a notification for reviewers, and agents often make several attempts. Running the same checks in the agent's own environment first catches most of those failures in minutes, with no runner.

Spotify's background coding agent runs format, build and test verifiers before it opens a pull request. If any of them fails, no pull request is created. Once they pass, a model acting as judge compares the diff with the original task. OpenAI's Agents SDK repositories spell out "verified" as a skill with the exact command sequence; `AGENTS.md` says when to run it, and work isn't marked complete until it passes. Stripe allows two CI runs per agent branch: the agent gets a single local retry on what the first run flagged, and a person takes the branch after the second.

## Apply it

Write one script that means "verified", and run the same script in CI:

```bash
#!/usr/bin/env bash
# scripts/verify.sh: what a change must pass before a pull request opens.
set -euo pipefail
pnpm install --frozen-lockfile
pnpm lint
pnpm exec tsc --noEmit --pretty false
pnpm exec vitest run --reporter=minimal
```

- CI calls it with `run: ./scripts/verify.sh`, so the local definition can't drift from the gate.
- `set -euo pipefail` stops at the first failing command and keeps its exit code.
- The quiet reporters from [agent-readable output](https://berrybox.io/playbooks/pr-volume/agent-readable-output.md) keep failures small enough for the agent's context.

Make it a rule in `AGENTS.md`, and in `CLAUDE.md` for Claude Code:

```markdown
Before opening or updating a pull request:
- Run `./scripts/verify.sh` after any change to code, tests, build files or CI configuration. Don't open or update the pull request until it passes.
- Docs-only changes can skip it.
- Never skip, delete or loosen a test, lint rule or type check to make it pass. If a failure is unrelated to your change, say so in the pull request description.
```

Enforce it where the agent runs. In Claude Code, a `Stop` hook can run the script when the agent tries to finish and exit with code 2 on failure, which sends the error back to the agent. Check `stop_hook_active` in the hook's input so a failure the agent can't fix doesn't loop forever. Spotify enforces its verifiers through the same kind of hook.

After pushing, have the agent wait for the required checks on the current head:

```bash
gh pr checks "$PR_NUMBER" --watch --required --fail-fast
```

- `gh pr checks` reads the pull request's current head commit, so results from an earlier push don't count. Shopify's River saw why this matters: after each force-push, "CI passed" notifications arrived for the heads it had just replaced.
- Cap the rounds. After two red CI runs, the agent should stop, describe what it tried and hand the pull request to a person.

## Keep it safe

- Passing locally isn't passing CI. Operating system, services, secrets and caches differ, so CI stays the gate. The script only catches the common failures earlier.
- Agents can make checks pass by weakening them. Spotify added its judge partly because agents disabled flaky tests or refactored beyond the task. In agent pull requests, review changes to tests, lint configuration and workflow files with extra care.
- The script should need no secrets or production credentials, because agents run it in environments you don't fully control.
- When CI gains a required check, add it to the script in the same pull request.

## Verify

- Ask an agent for a small change and confirm, from its transcript or the pull request description, that it ran the script before opening the pull request.
- For the last 20 agent pull requests before and after the change, count failed runs per pull request with `gh run list --branch <branch> --event pull_request --json conclusion --jq 'map(select(.conclusion == "failure")) | length'`. Failures the script covers should mostly disappear.
- Rerun the [baseline](https://berrybox.io/playbooks/baseline.md). `pull_request` runs and runner minutes per merged agent pull request should fall.

## Sources

- Spotify: [Spotify Engineering: block an agent's pull request until format, build and test verifiers pass, then have an LLM judge review the diff](https://engineering.atspotify.com/2025/12/feedback-loops-background-coding-agents-part-3). Across thousands of agent sessions, the judge vetoes about a quarter, and the agent course-corrects about half the time.
- OpenAI: [OpenAI Developers blog: require a code-change verification skill before agent work counts as done in the Agents SDK repositories](https://developers.openai.com/blog/skills-agents-sdk)
- Stripe: [Stripe Dev blog: agents fix lint locally before pushing and get one round of CI fixes before a human takes over](https://stripe.dev/blog/minions-stripes-one-shot-end-to-end-coding-agents-part-2)
- Shopify: [Shopify Engineering: River retriggers CI after each rebase and waits for the verdict on the current head](https://shopify.engineering/river-vulnerability-remediation)
