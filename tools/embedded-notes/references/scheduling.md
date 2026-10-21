# Scheduling

Plans are explicit TOML files under `.embedded-notes/plans/`:

```toml
id = "weekly-embedded-notes"
schedule = "0 20 * * 1"
timezone = "Asia/Shanghai"
publish = true
topics = ["STM32 外设", "RTOS 任务调度", "嵌入式调试"]

[[sources]]
type = "note"
note_id = "embedded-reference"
```

Run a plan with:

```text
python scripts/notesctl.py plan run --site-root <hugo-site> --plan-id weekly-embedded-notes
```

`plan run` preflights synchronization and then invokes the configured generator command once per topic. Each invocation is forced to `mode: single` and `count: 1`; a multi-topic plan is only a loop over this single-note path. The command receives `{plan_file}`, `{plan_id}`, `{run_id}`, `{topic}`, `{index}`, `{count}`, `{request_id}`, `{prompt}`, and `{site_root}` substitutions. Configure a headless `codex exec` command or another generator explicitly; the Python tool does not pretend to generate AI content by itself.

Pass `--run-id <stable-id>` when retrying a partially failed plan so completed items reuse their request IDs and remain idempotent.

For example, a local configuration may use a command shaped like:

```toml
[generator]
command = ["codex", "exec", "--ephemeral", "--color", "never", "--sandbox", "workspace-write", "--approve-for-me", "--cd", "{site_root}", "{prompt}"]
```

This is also the default written by `notesctl init`. Before installing a schedule, run `codex --version` and `codex login status` as the same operating-system user that will own the task. `schedule install` verifies that the configured generator executable is resolvable and captures the current `PATH` in the ignored machine-local wrapper. Keep any environment-specific overrides in configuration rather than in a note or web source. Do not use `--dangerously-bypass-approvals-and-sandbox` unless the entire host is an intentionally isolated disposable environment.

Install or remove the local Windows scheduled task with:

```text
python scripts/notesctl.py schedule install --site-root <hugo-site> --plan-id weekly-embedded-notes
python scripts/notesctl.py schedule remove --site-root <hugo-site> --plan-id weekly-embedded-notes
```

Windows uses Task Scheduler for the supported daily/weekly cron shapes. Because Task Scheduler runs in the Windows system timezone, installation verifies that a declared IANA timezone maps to the active Windows timezone and stops on a mismatch. Omit `timezone` or use `local` only when host-local scheduling is intentional. Unsupported cron expressions are reported instead of being silently approximated.
