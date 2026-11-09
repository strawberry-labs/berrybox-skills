# Move IO-heavy work onto faster storage

When unpacking, installing or database writes dominate a job, put the workspace, package caches, build outputs and test data on the fastest storage the runner has, such as a Windows Dev Drive, a local NVMe disk or tmpfs.

- Playbook: [Give the long pole the right machine](https://berrybox.io/playbooks/runners.md)
- Saves: wait time and runner minutes
- Risk: medium
- Web page: https://berrybox.io/playbooks/runners/fast-disk

## Signals in your baseline

- On Windows, cache restores, archive extraction, package installs or Cargo builds take minutes while the same steps on Linux take a fraction of that.
- Steps that write many small files, such as node_modules installs, extraction or test databases, dominate the long pole while compile steps are short.
- Integration tests run Postgres, MySQL or an object store and spend much of their time writing and syncing to disk.
- A runner with more cores sped up compile steps but not installs or extraction.

## Why it works

Some steps wait on the disk, not the CPU: extracting an archive of a few hundred thousand files, linking `node_modules`, writing Cargo or Bazel output trees, or a database that syncs every commit to disk. Storage varies a lot between runners. Some VMs boot from a network-attached disk, Windows runs file system filters such as antivirus on file operations, and a local NVMe disk or RAM is far faster than either. Moving the hot directories to faster storage speeds those steps up without touching your code. More cores won't, which is why a [bigger runner](https://berrybox.io/playbooks/runners/bigger-runner.md) can leave these steps unchanged.

## Apply it

Find the IO-heavy steps in your [baseline](https://berrybox.io/playbooks/baseline.md) step table, note which directories they read and write, and move those directories.

### Windows: use a Dev Drive

A Dev Drive is a ReFS volume tuned for developer workloads, and you can create one in a few seconds as a virtual disk. On GitHub-hosted runners it needs a Windows Server 2025 image (`windows-2025` or `windows-latest`). Some Windows runners also have a fast temporary `D:` drive, which the uv project found as fast as a Dev Drive or faster, so use `D:` where it exists. GitHub's larger Windows runners don't have one.

```yaml
- name: Create a Dev Drive
  shell: pwsh
  run: |
    $volume = New-VHD -Path "$env:RUNNER_TEMP\devdrive.vhdx" -SizeBytes 50GB -Dynamic |
      Mount-VHD -Passthru |
      Initialize-Disk -Passthru |
      New-Partition -AssignDriveLetter -UseMaximumSize |
      Format-Volume -DevDrive -Confirm:$false -Force
    $drive = "$($volume.DriveLetter):"
    "DEV_DRIVE=$drive" >> $env:GITHUB_ENV
    "npm_config_cache=$drive\npm-cache" >> $env:GITHUB_ENV
    "CARGO_TARGET_DIR=$drive\target" >> $env:GITHUB_ENV
    Write-Output "Dev Drive mounted at $drive"
```

- `-Dynamic` makes the virtual disk grow only as files are written, so 50 GB is a ceiling, not an allocation.
- Writing to `GITHUB_ENV` points later steps' package caches and build outputs at the new drive. Add the variables your tools read, for example `GRADLE_USER_HOME` or `NUGET_PACKAGES`.
- Run this before any step that restores or writes those directories, and make cache `path` entries match the new locations.

To put the checkout itself on the drive, VS Code mounts the volume as a folder at the workspace's parent, so paths stay the same and `actions/checkout` sees an ordinary empty directory.

### Linux: keep test databases in memory

```yaml
services:
  postgres:
    image: postgres:18
    env:
      POSTGRES_PASSWORD: postgres
    ports:
      - 5432:5432
    options: >-
      --tmpfs /var/lib/postgresql
      --health-cmd "pg_isready -U postgres"
      --health-interval 2s
      --health-timeout 5s
      --health-retries 30
```

- From Postgres 18 the image keeps its data under `/var/lib/postgresql`. For 17 and older, mount `/var/lib/postgresql/data`.
- A tmpfs lives in RAM and disappears with the container, which is what a throwaway test database needs.
- For processes you start yourself, `eatmydata` (an apt package) turns `fsync` into a no-op. It doesn't work for statically linked programs, such as most Go binaries.

### Self-hosted runners

Pick instance types with local NVMe for IO-bound jobs, and put the runner's work directory and Docker data root on it. Network block storage is the slow path Canva moved away from.

## Keep it safe

- **Decide how setup fails.** `New-VHD` needs Hyper-V, which some self-hosted and third-party Windows runners lack, so test the step on your runner type. If the Dev Drive can't be created, either fail the job (Codex does) or fall back to the OS disk with a visible warning (VS Code does). Don't fall back silently, or a slow job will look like a regression in your code.
- **Paths change.** Tools that hardcode `C:\` can break, and caches whose key or path includes the old location will miss after the move. WSL can't open folders on a volume mounted inside `C:`, so VS Code left its WSL job on the OS disk.
- **Leave antivirus on.** `fsutil devdrv enable /disallowAv` detaches antivirus filters from every Dev Drive on the machine. The default performance mode is the safer trade.
- **Durability tests.** tmpfs and `eatmydata` remove the crash safety that recovery tests check. Keep those tests on a real disk.
- **Memory.** tmpfs data counts against the runner's RAM; a large dataset can get the job killed.
- **Secrets and checks.** On ephemeral runners the drive disappears with the VM. On reused self-hosted runners, wipe it between jobs. This play renames no jobs.

## Verify

- Compare the IO-heavy steps' p50 and p90 with the baseline on the same runner type, and check the log line that says which drive was used.
- Compare the whole job's duration, since creating the drive adds a few seconds.
- Confirm the same tests ran and passed and the same checks reported.

## Sources

- Microsoft: [vscode: mount a Dev Drive for the Windows test jobs on larger runners that have no temporary disk](https://github.com/microsoft/vscode/pull/343812). On the larger runner, extracting the node_modules archive (219k files, 6.3 GB) took 100-162 seconds on the network-attached OS disk and 43-45 seconds on a Dev Drive.
- OpenAI: [codex: route Cargo and Bazel build, cache and temp directories through a Dev Drive on Windows](https://github.com/openai/codex/pull/31357)
- Canva: [Canva Engineering: run the IO-bound build-all step on instances with local SSDs instead of EBS](https://www.canva.dev/blog/engineering/faster-ci-builds-at-canva/). Moving the step to i4i.8xlarge instances with multiple local SSDs cut its runtime from up to 3 hours to around 15 minutes.
- Materialize: [Materialize blog: run filesystem-heavy tests under libeatmydata, with tmpfs as the alternative](https://materialize.com/blog/speeding-up-materialize-ci/)
