# Shorten the path that ends the run

Find the chain of jobs that decides when a run finishes, then remove waits that aren't dependencies, build once, move independent work off the longest job and keep the full matrix where it pays off.

Web page: https://berrybox.io/playbooks/critical-path

## Signals in your baseline

- The baseline's "Most common critical path" chains three or more jobs, and a job on it never uses an artifact or output from the job it waits for.
- The same "Long-pole job" shows up in most runs, and its p50 duration is close to the workflow's p50 wall time.
- Two or more jobs in one workflow install dependencies and run the same build before their own step.
- Many jobs take well under two minutes, and checkout and setup fill most of that time.
- Pull request runs expand a matrix of several operating systems or runtime versions.

A run finishes when the last job on its critical path finishes. Speeding up any other job saves runner minutes but no waiting. These plays change the shape of the job graph: they remove waits that aren't real dependencies, stop several jobs from building the same thing, move independent work off the longest job, fold tiny jobs together and keep the full matrix for the runs where it finds bugs.

## Confirm it in your baseline

- Read the **Most common critical path** for each workflow in the [baseline](https://berrybox.io/playbooks/baseline.md) report. For every `needs` on that chain, check whether the later job downloads an artifact, reads an output or uses something the earlier job published. A `needs` that only sets the order is a wait you can remove.
- Check the **Long-pole job** and its **Share of runs**. Its rows in **Steps inside the long-pole jobs** show which steps could run somewhere else.
- Search the workflow for build commands that appear in several jobs, such as `npm run build`, `cargo build` or `docker build`.
- Compare **Runner min/run (p50)** with **p50 wall**. Many short jobs push minutes up, because each pays for its own setup and GitHub-hosted runners bill every job in whole minutes.

## Order of work

Start with [dropping unused needs](https://berrybox.io/playbooks/critical-path/parallelize-independent-jobs.md): it's often a one-line change and the biggest wall-clock win. [Build once](https://berrybox.io/playbooks/critical-path/build-once.md) next if several jobs compile the same code. Splitting the long pole and merging tiny jobs pull in opposite directions, so decide job by job: split when the moved work is much longer than a runner's setup, merge when setup is most of the job. Running steps in parallel is a small change inside one job. Trim the matrix last, because it changes what a pull request tests and needs a full run somewhere else.

## Plays

- [Start independent jobs together by dropping needs they don't use](https://berrybox.io/playbooks/critical-path/parallelize-independent-jobs.md): Keep a needs edge only where the later job uses the earlier job's artifact, output or side effect, let every other job start when the run starts, and gate merges on one aggregate job. Saves wait time; low risk.
- [Build once and pass the output to the jobs that need it](https://berrybox.io/playbooks/critical-path/build-once.md): Compile, bundle or build the image in one job, upload the result as an artifact, and have test shards, end-to-end jobs and packaging download it instead of repeating the same build on every runner. Saves wait time and runner minutes; medium risk.
- [Split independent work out of the long-pole job](https://berrybox.io/playbooks/critical-path/split-the-long-pole.md): When one job sets the run's wall time, move steps that don't use the rest of its output into a parallel job, keep the required check name on an aggregate job, and split only when the moved work dwarfs a job's setup. Saves wait time; low risk.
- [Combine short checks whose setup takes longer than the work](https://berrybox.io/playbooks/critical-path/merge-tiny-jobs.md): Run lint, format, type and other short checks as steps of one job that checks out and installs once, so each check stops paying for its own runner, setup and rounded-up minute. Saves runner minutes; low risk.
- [Run independent steps at the same time inside a job](https://berrybox.io/playbooks/critical-path/overlap-setup.md): In the long-pole job, start independent steps such as image pulls, dependency installs, per-target builds and packaging together, wait for them before the step that needs their results, and keep every failure visible. Saves wait time; low risk.
- [Run a reduced matrix on pull requests and the full matrix later](https://berrybox.io/playbooks/critical-path/trim-the-matrix.md): Test pull requests on the few platforms and versions that catch most breakage, run every combination in the merge queue, on the default branch or on a schedule, and require one aggregate check so the legs can change. Saves wait time and runner minutes; medium risk.
