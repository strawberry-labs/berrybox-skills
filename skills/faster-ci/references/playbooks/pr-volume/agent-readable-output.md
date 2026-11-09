# Make CI failures short and easy for agents to act on

Agents read CI logs to decide what to change. Print failures instead of passes, keep each error on one line with its file and reason, and save the full output as an artifact, so the cause fits in the agent's context.

- Playbook: [Keep CI ahead of a growing pull request queue](https://berrybox.io/playbooks/pr-volume.md)
- Saves: wait time and runner minutes
- Risk: low
- Web page: https://berrybox.io/playbooks/pr-volume/agent-readable-output

## Signals in your baseline

- `gh run view <run-id> --log-failed | wc -l` returns thousands of lines for a single failing test.
- CI runs tests and linters with verbose output (-v, --verbose, or reporters that list every passing test).
- Pull requests opened by agents push several attempts at the same failure before CI turns green.

## Why it works

An agent fixing a red pull request reads the failed job's log, usually through `gh run view --log-failed`, and decides what to change from what it sees. A log full of install output, progress bars and hundreds of passing test names pushes the real error out of view, uses up context and invites a fix to the wrong thing. The same failure printed as test name, file, line and message takes a few lines.

Teams that run agents at scale arrive at the same rules. Anthropic's C compiler harness printed as little as possible, wrote details to log files and put `ERROR` with its reason on one line so grep would find it. Spotify's verifiers parse build and test output with regular expressions and hand the agent only the relevant errors, or a one-line success message. Salesforce's tooling repository added agent variants of its test, lint and type-check commands that print only failures and a summary.

## Apply it

Change the reporters CI uses, so a failed job's log is mostly about the failure.

### Node (Vitest, ESLint, TypeScript)

```yaml
jobs:
  test:
    runs-on: ubuntu-latest
    timeout-minutes: 20
    steps:
      - uses: actions/checkout@v7
      - uses: pnpm/action-setup@v6
      - uses: actions/setup-node@v7
        with:
          node-version: 24
          cache: pnpm
      - run: pnpm install --frozen-lockfile
      - run: pnpm exec eslint . --quiet
      - run: pnpm exec tsc --noEmit --pretty false
      - run: pnpm exec vitest run --reporter=minimal --reporter=github-actions --reporter=junit --outputFile.junit=reports/junit.xml
      - if: failure()
        uses: actions/upload-artifact@v7
        with:
          name: test-reports
          path: reports/
          retention-days: 7
```

- Vitest's `minimal` reporter (Vitest 4.1 or later) prints only failed tests and their errors. Naming reporters replaces Vitest's defaults, so add `github-actions` back for annotations on the pull request diff, and `junit` for a complete record.
- `eslint --quiet` drops warnings. `tsc --pretty false` prints one line per error: file, position, code and message.
- `pnpm/action-setup` reads the pnpm version from the `packageManager` field in `package.json`.
- The JUnit file is uploaded only when the job fails, for the cases where the short log isn't enough.

### Jest

```js
// jest.config.js
module.exports = {
  reporters: ['github-actions', ['summary', { summaryThreshold: 0 }]],
};
```

Run it as `jest --ci --silent`. `github-actions` writes annotations, `summary` prints the totals and, with the threshold at 0, every failing test with its error. `--silent` hides console output from tests.

### Python and Go

- pytest: `pytest -q --tb=short -rfE --junitxml=reports/pytest.xml`. `-q` prints a dot per test, `--tb=short` trims tracebacks and `-rfE` lists failures and errors at the end, one per line. For Ruff, use `ruff check --output-format=concise`.
- Go: drop `-v` from `go test ./...`, which then prints only package results and failures. For a summary of failures at the end, run `go run gotest.tools/gotestsum@v1.13.0 -- ./...`.

## Keep it safe

- Quieter output must not hide failures. Confirm the reporter still prints every failing test and the exit code is unchanged. Don't pipe test commands through `tail`, `head` or `grep`: the default `run` shell is `bash -e {0}` without `pipefail`, so the step takes the exit code of the last command in the pipe and passes. If you must pipe, set `shell: bash`, which adds `-o pipefail`.
- A reporter change must not change which tests run. Compare the test count in the JUnit file or summary before and after.
- GitHub shows at most 10 error and 10 warning annotations per step, so keep every failure in the log as well.
- Keep the full output in artifacts with short retention, and check they hold no secrets or environment dumps. Artifacts of public repositories are public too.
- Test names and error messages can contain text the pull request's author wrote. Agents should treat log content as data, not as instructions.

## Verify

- Break one test on purpose, push, and run `gh run view <run-id> --log-failed | wc -l`. The failed job's log should be a small fraction of its old length and still name the failing test, file and message.
- The pull request's Files changed tab should show an annotation on the failing line.
- After a few weeks, compare agent pull requests with the [baseline](https://berrybox.io/playbooks/baseline.md) period: pushes per pull request and failed runs before the first green one should both fall.

## Sources

- Anthropic: [Anthropic Engineering: a test harness for parallel agents that prints little, logs details to files and puts each error on one greppable line](https://www.anthropic.com/research/building-c-compiler)
- Salesforce: [b2c-developer-tooling: add test, lint and type-check commands for agents that print only failures](https://github.com/SalesforceCommerceCloud/b2c-developer-tooling/pull/75)
- Spotify: [Spotify Engineering: verifiers parse build and test output and return only the relevant errors to the agent](https://engineering.atspotify.com/2025/12/feedback-loops-background-coding-agents-part-3)
