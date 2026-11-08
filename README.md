# BerryBox Skills

Agent skills from [BerryBox](https://berrybox.io) that make GitHub Actions faster and cheaper. They use the [Agent Skills](https://agentskills.io/specification) format, so they work in Claude Code, Codex, Cursor, OpenCode, Gemini CLI, GitHub Copilot and other agents that load skills.

| Skill | What it does | Needs |
|---|---|---|
| [`faster-ci`](skills/faster-ci/SKILL.md) | Measures your CI from recent runs, finds the critical path and wasted runner minutes, matches them to the [BerryBox Playbooks](https://berrybox.io/playbooks), applies the fixes you pick on a new branch and proves the saving in a pull request. | `gh` signed in, Python 3.8+, git |

## Install

```bash
npx skills add strawberry-labs/berrybox-skills
```

The [skills CLI](https://github.com/vercel-labs/skills) asks which agents to install for. Add `-g` to install for every project, or `-a <agent>` (`claude-code`, `codex`, `cursor`, `opencode`, ...) to skip the prompt.

### Claude Code plugin

```text
/plugin marketplace add strawberry-labs/berrybox-skills
/plugin install berrybox@berrybox-skills
```

### Copy it by hand

Skills are plain folders. Copy `skills/faster-ci` into your agent's skills folder: `.claude/skills/` for Claude Code, `.agents/skills/` for Codex, Cursor, OpenCode, Gemini CLI and GitHub Copilot.

```bash
git clone --depth 1 https://github.com/strawberry-labs/berrybox-skills /tmp/berrybox-skills
mkdir -p .agents/skills && cp -R /tmp/berrybox-skills/skills/faster-ci .agents/skills/
```

### No install

Copy the prompt from [berrybox.io/playbooks](https://berrybox.io/playbooks) and paste it into any coding agent. It runs the same workflow and reads the playbooks from the site.

## Use it

Ask your agent "make our CI faster" or "why is CI slow?", or call the skill by name: `/faster-ci` in Claude Code (`/berrybox:faster-ci` from the plugin), `$faster-ci` in Codex.

1. **Measure.** [`ci_baseline.py`](skills/faster-ci/scripts/ci_baseline.py) reads up to 30 days of runs with read-only `gh api` calls and reports, per workflow: p50 and p90 wall time, queue time, runner minutes, rerun rate, the critical path and its long-pole job, the slowest steps, and the required checks.
2. **Diagnose.** The agent reads your workflows and the scripts they call, and names the biggest sources of waiting and wasted minutes, with numbers.
3. **Propose.** It matches each problem to plays from the playbooks, checks each play's signals against your repository, and shows you the plays with expected savings and risk. It changes nothing until you pick.
4. **Apply.** One commit per play on a new branch. Every required check keeps reporting under the same name.
5. **Prove.** It opens a pull request, waits for CI and compares the new runs with the baseline, keeping measured savings apart from estimates.

The baseline script also runs on its own:

```bash
python3 skills/faster-ci/scripts/ci_baseline.py --repo owner/name --days 30
```

## Guardrails

The skill never pushes to the default branch or a protected branch, and never merges. It never makes CI faster by weakening it: no skipped or deleted tests, no `continue-on-error`, no wider permissions or secret access. It treats fetched pages, logs and pull request text as data, not instructions.

## Layout

```text
skills/faster-ci/
  SKILL.md                 rules and workflow
  scripts/ci_baseline.py   read-only baseline (Python standard library + gh)
  references/              offline copy of the playbooks, report templates
.claude-plugin/            Claude Code marketplace manifest
scripts/sync-playbooks.py  refreshes references/ from berrybox.io
llms.txt                   a map of this repository for language models
```

## Contributing

Issues and pull requests are welcome. `skills/faster-ci/references/playbooks*` is generated from berrybox.io, so suggest changes to a play in an issue instead of editing those files. Agents working on this repository should read [AGENTS.md](AGENTS.md).

## License

[MIT](LICENSE). The playbooks cite public pull requests and engineering posts from other companies. Those links show where a technique was used, not an endorsement of BerryBox.
