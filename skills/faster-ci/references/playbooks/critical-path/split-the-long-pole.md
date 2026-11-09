# Split independent work out of the long-pole job

When one job sets the run's wall time, move steps that don't use the rest of its output into a parallel job, keep the required check name on an aggregate job, and split only when the moved work dwarfs a job's setup.

- Playbook: [Shorten the path that ends the run](https://berrybox.io/playbooks/critical-path.md)
- Saves: wait time
- Risk: low
- Web page: https://berrybox.io/playbooks/critical-path/split-the-long-pole

## Signals in your baseline

- The same "Long-pole job" appears in most runs of a workflow, with a high "Share of runs".
- The long pole's rows in "Steps inside the long-pole jobs" show two or more long steps that don't use each other's output, such as unit tests followed by integration tests, or a second platform's compile after the first platform's tests.
- Other jobs in the run finish long before the long pole, so most runners sit idle while it works.

## Why it works

The run ends when the long pole ends. If that job runs unit tests, then integration tests, then a second platform's compile, and none of those steps use each other's output, they wait for each other only because they share a job. Give one of them its own job and both parts run at the same time on separate runners. The long pole shrinks to the longer part plus one setup.

Every new job pays for its own queue time, checkout, toolchain and dependency install, and that runner time is billed too. A split pays off only when the work you move is much longer than that setup. Moving a two-minute step into a job with three minutes of setup makes the run slower and more expensive. That case calls for the opposite play, [merge tiny jobs](https://berrybox.io/playbooks/critical-path/merge-tiny-jobs.md). If the runner has idle cores, running the two parts as [parallel steps in the same job](https://berrybox.io/playbooks/critical-path/overlap-setup.md) avoids the second setup.

## Apply it

1. Take the long pole from the **Critical paths** table of the [baseline](https://berrybox.io/playbooks/baseline.md) and read its rows in **Steps inside the long-pole jobs**.
2. Find a block of steps that doesn't read files the rest of the job produces. Common candidates are integration or snapshot tests after unit tests, a second platform's compile, docs builds and packaging checks.
3. Move that block into a new job. Put both jobs behind an aggregate job that keeps the old job's name, so branch protection keeps matching.

```yaml
jobs:
  test-unit:
    runs-on: ubuntu-24.04
    steps:
      - uses: actions/checkout@v7
      - uses: actions/setup-python@v7
        with:
          python-version: "3.13"
          cache: pip
      - run: pip install -r requirements-dev.txt
      - run: pytest tests/unit

  test-integration:
    runs-on: ubuntu-24.04
    steps:
      - uses: actions/checkout@v7
      - uses: actions/setup-python@v7
        with:
          python-version: "3.13"
          cache: pip
      - run: pip install -r requirements-dev.txt
      - run: pytest tests/integration

  test:
    if: always()
    needs: [test-unit, test-integration]
    runs-on: ubuntu-24.04
    steps:
      - name: Require both parts to pass
        run: |
          test "${{ needs.test-unit.result }}" = success
          test "${{ needs.test-integration.result }}" = success
```

- The aggregate job is called `test`, like the job it replaces, so the required check keeps matching without a change to branch protection.
- `if: always()` makes the gate run and report when one part fails. Without it the gate is skipped, and a skipped required check may not block the merge.
- Comparing each result with `success` also fails the gate when a part was cancelled or skipped.

## Keep it safe

- Look for hidden ordering before you move a block. Later steps may rely on files or state from earlier ones: a built binary, generated code, a migrated database, a running service. Run the new job on a branch and read its first failures.
- Make sure every test still runs exactly once. Splitting by directory can drop tests that live in neither directory, or run some twice. Compare test counts before and after.
- Keep required check names stable. If you rename or remove a required job instead of giving its name to the aggregate, every new pull request waits forever for a check that never reports.
- Give the new job only what it needs. Don't copy `secrets: inherit` or a broad `permissions` block from the old job by default.
- Watch the minutes. Each split adds one setup's worth of runner time to every run. If the moved block isn't clearly longer than that setup, put it back.

## Verify

- In the branch baseline, the **Long-pole job** should change or its **p50 long-pole duration** should drop, and p50 wall should fall by about the moved block's duration minus one setup.
- **Runner min/run (p50)** should rise by about one setup. If it rises much more, the new job installs more than it needs.
- The test counts of the two new jobs should add up to the old job's count.

## Sources

- OpenAI: [openai-cli: compile the Windows tests in a parallel job instead of after the Linux tests, behind the same test gate](https://github.com/openai/openai-cli/pull/489). The required test gate finished 10m 17s after the Linux job started, against 12m 18s for a contemporaneous control run (2m 01s, 16% faster).
- Stripe: [stripe-ios: split the combined installation and integration job back into two parallel jobs](https://github.com/stripe/stripe-ios/pull/7334). The combined job took about 27 minutes; split, installation took about 11 to 12 minutes and integration about 13, running in parallel.
- Stripe: [stripe-ios: split the framework unit tests and move snapshot tests into a separate job](https://github.com/stripe/stripe-ios/pull/7332). Framework tests went from about 22 minutes to about 12 to 14.
- Linear: [Linear Now: move the cache-marker write out of the pre-merge check into a job that gates nothing](https://linear.app/now/ci-bottleneck-reworked). The move shaved 42 seconds from the merge path for every API pull request and merge-queue entry.
