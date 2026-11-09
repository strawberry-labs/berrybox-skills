# Move lint and type checks to native tools without losing rules

Type-check with TypeScript 7's native compiler and lint with Oxlint or Ruff, after you map every rule you run today and prove the new setup still fails on the problems the old one caught.

- Playbook: [Build less, and build it faster](https://berrybox.io/playbooks/slow-builds.md)
- Saves: wait time and runner minutes
- Risk: medium
- Web page: https://berrybox.io/playbooks/slow-builds/native-tools

## Signals in your baseline

- The lint or type-check job is the long pole on pull requests, and its steps run `tsc`, `eslint`, `flake8`, `isort` or `pylint`.
- `package.json` pins `typescript` below 7, and `tsc --noEmit` takes minutes.
- The ESLint config sets `parserOptions.project` or `projectService`, so every lint run builds the whole TypeScript program first.
- Python lint runs flake8, isort and Black as separate steps or tox environments.

## Why it works

TypeScript 7 is a native port of the compiler. It type-checks on several threads (four checkers by default), and Microsoft reports 8x to 12x faster full builds than TypeScript 6. Oxlint and Ruff reimplement hundreds of ESLint, flake8 and isort rules in Rust and lint files in parallel. Type-aware lint rules cost the most: they make ESLint build the whole TypeScript program before it lints anything, so lint pays for most of a type check.

Speed isn't the risk. Coverage is. A rule that quietly disappears lets code through that CI used to reject, so map the rules first and prove the new setup fails where the old one did.

## Apply it

### Take inventory

- Save the effective ESLint config for one file from each `files` override: `npx eslint --print-config src/index.ts > eslint-before.json`.
- Run `npx @oxlint/migrate --details` to generate `.oxlintrc.json` and list the rules Oxlint can't take.
- For Python, list every flake8 plugin and isort setting, and map each to its Ruff prefix (`B` for flake8-bugbear, `I` for isort).

### TypeScript 7 for type checks

Adopt TypeScript 6.0 first: 7.0 turns everything 6.0 deprecated into hard errors. Then install 7.0. It ships no compiler API yet, so if typescript-eslint or another tool imports `typescript`, keep 6.0 under that name and add 7.0 under an alias:

```shell
npm install -D typescript@npm:@typescript/typescript6 @typescript/native@npm:typescript@^7.0.2
```

`npx tsc` now runs 7.0, and `tsc6` runs 6.0. Projects that type-check Vue, Svelte, Astro or MDX files need 6.0 for now.

### Oxlint with ESLint for the rest

```yaml
name: lint
on:
  pull_request:
  push:
    branches: [main]

permissions:
  contents: read

jobs:
  lint:
    runs-on: ubuntu-latest
    timeout-minutes: 15
    steps:
      - uses: actions/checkout@v7
      - uses: actions/setup-node@v7
        with:
          node-version: 24
          cache: npm
      - run: npm ci
      - run: npx oxlint --deny-warnings --format github
      - run: npx tsc --noEmit
      - run: npx eslint .
```

- Oxlint runs before the slower steps, so a lint error fails in seconds. `--format github` turns its findings into pull request annotations.
- ESLint keeps only the rules Oxlint lacks. Add `...(await oxlint.buildFromConfigFile("./.oxlintrc.json"))` from `eslint-plugin-oxlint` as the last entry in `eslint.config.js`. It turns off every ESLint rule Oxlint already runs.
- Pin `oxlint` to an exact version in `package.json`. New releases add rules to the default categories.

Type-aware rules are what keep ESLint slow. Linear rewrote its custom ones to inspect syntax only, which let ESLint drop TypeScript entirely. Where you can't, move the typed rules to their own job off the critical path.

### Ruff for Python

```yaml
      - uses: astral-sh/ruff-action@278981a28ce3188b1e39527901f38254bf3aac89 # v4.1.0
      - uses: astral-sh/ruff-action@278981a28ce3188b1e39527901f38254bf3aac89 # v4.1.0
        with:
          args: format --check
```

The first step runs `ruff check` (the default `args`). The action reads the Ruff version from `pyproject.toml` and falls back to the latest release, so pin it there to keep CI and laptops in step. Set `select` under `[tool.ruff.lint]` to cover your old plugins, for example `["E", "F", "W", "I", "B"]`.

## Keep it safe

- **Prove parity.** Every rule in `eslint-before.json` should end up enabled in `.oxlintrc.json` or in ESLint, never both. Kibana ran `eslint --print-config` on a file from every override to confirm no rule ran twice.
- **Prove it fails.** On a scratch branch, plant a violation for each rule you care about and confirm the job goes red. Shopify did this for `no-unused-vars` and an import guard.
- **Disable comments.** `eslint-disable` comments that name moved rules look unused to ESLint, and `--fix` can strip them. Kibana turned off its unused-directive rule while it moves 609 such comments to `oxlint-disable`; `@oxlint/migrate --replace-eslint-comments` can rewrite them.
- **Formatting churn.** Adding `ruff format` rewrites many files. Land it as its own commit and list it in `.git-blame-ignore-revs`.
- **Memory.** More `--checkers` speed large builds but use more memory. Keep the default on 2-vCPU runners unless you measure.
- **Required checks.** Keep the job names. If a required `flake8` job becomes `ruff`, update branch protection in the same change.

## Verify

- Compare the lint and type-check step p50s with the [baseline](https://berrybox.io/playbooks/baseline.md) over five or more runs.
- On the same commit, `tsc` and `tsc6` should both pass, and Oxlint plus ESLint should report the same findings the old setup did. Explain every difference.
- The planted violations fail the job, and the same set of checks reports on the pull request.

## Sources

- Linear: [Linear blog: switch type checks to tsgo and rewrite type-aware lint rules to work on syntax alone](https://linear.app/now/ci-bottleneck-reworked). tsgo cut the weekly median of the `tsc` check by 73%. Dropping TypeScript from ESLint cut API lint time by 68% and full-repository lint time by 55%.
- Elastic: [kibana: run Oxlint ahead of ESLint in one CI step and turn off the 57 ESLint rules Oxlint now owns](https://github.com/elastic/kibana/pull/288513)
- Shopify: [shopify-app-js: replace ESLint with a pinned Oxlint and prove key rules fire by planting violations](https://github.com/Shopify/shopify-app-js/pull/3347)
- Spotify: [luigi: replace flake8 and isort with Ruff and add the Ruff formatter](https://github.com/spotify/luigi/pull/3395)
