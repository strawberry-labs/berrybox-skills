# Run only what a change can affect

On pull requests, run only the tests and packages a change can reach and reuse results for inputs that already passed, while the merge queue, the default branch or a nightly run still runs everything.

Web page: https://berrybox.io/playbooks/test-selection

## Signals in your baseline

- A test or build job is the long pole on pull requests, and its duration doesn't change with the size of the diff.
- A monorepo runs every package's checks when a change touches one package.
- Slow checks rerun on pushes that didn't change any file they read.

The other playbooks make each check cheaper. These plays run fewer checks. A pull request only needs the tests a change can reach, as long as something still runs everything before or soon after the merge. That makes this the riskiest playbook: a selection that misses a dependency lets a break through. Every play here keeps a full run and falls back to it when shared inputs such as lockfiles, CI config or build tooling change.

## Confirm it in your baseline

- In **Slowest jobs**, find the test and build jobs on the critical path. If small and large pull requests take about the same time, every run is doing the full set.
- Run `gh pr list --state merged --limit 100 --json number,files` and count the pull requests that stay inside one directory or package. Selection pays off when most of them do.
- In **Workflows**, check that `push` runs on the default branch, `merge_group` runs or a schedule already exist and pass reliably. They become your safety net. A high rerun rate means you should fix [flaky tests](https://berrybox.io/playbooks/flaky-tests.md) first.
- Look in **Steps inside the long-pole jobs** for slow checks, such as API diffs or end-to-end builds, that take the same time whether or not their inputs changed.

## Order of work

In a monorepo, start with [affected packages](https://berrybox.io/playbooks/test-selection/affected-packages.md): the workspace tool already knows the package graph, so the risk is lowest. Next, [reuse unchanged results](https://berrybox.io/playbooks/test-selection/reuse-unchanged-results.md) for slow, deterministic checks. Apply [affected tests](https://berrybox.io/playbooks/test-selection/affected-tests.md) last, once a full run in the merge queue or on the default branch is in place to catch what selection misses.

## Plays

- [Select the tests each change needs, and keep a full-suite backstop](https://berrybox.io/playbooks/test-selection/affected-tests.md): On pull requests, run only the tests that depend on what a change touched, fall back to the full suite when shared inputs change, and keep running everything in the merge queue, on the default branch and nightly. Saves wait time and runner minutes; high risk.
- [Build and test only the affected packages in a monorepo](https://berrybox.io/playbooks/test-selection/affected-packages.md): Let the workspace tool map a change to the packages it touches and every package that depends on them, run tasks for that set only, and run everything when root config, lockfiles or CI files change. Saves wait time and runner minutes; medium risk.
- [Reuse a passing result when a check's inputs haven't changed](https://berrybox.io/playbooks/test-selection/reuse-unchanged-results.md): Key each slow, deterministic check on a hash of everything it reads, record a pass when it succeeds, and skip the work when the same inputs already passed, while the check still reports under its usual name. Saves wait time and runner minutes; medium risk.
