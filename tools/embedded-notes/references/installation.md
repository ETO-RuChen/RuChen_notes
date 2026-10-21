# Installation

The local Windows Skill requires Python 3.11 or newer, Git, Hugo Extended, and an authenticated Codex CLI for scheduled generation.

Install it from the Skill source checkout:

```text
python scripts/install_skill.py
```

The installer uses `$CODEX_HOME/skills/embedded-notes` when `CODEX_HOME` is set and otherwise uses `~/.codex/skills/embedded-notes`. To update an existing installation while preserving a timestamped backup:

```text
python scripts/install_skill.py --update
```

An update stages the new Skill first, backs up the installed version, and then replaces the installed directory as a unit. Files removed from the source are therefore removed from the installed copy instead of surviving as stale behavior.

The Hugo repository remains separate and keeps `.embedded-notes/config.toml` in that repository. Credentials stay in the local Git credential helper, SSH agent, or Codex authentication store.

When the Skill source is vendored at `tools/embedded-notes` in that repository, a fresh clone can install it without a second machine-specific source location:

```text
python tools/embedded-notes/scripts/install_skill.py --update
```

The installed copy under `$CODEX_HOME` is runtime state. Make changes in the versioned `tools/embedded-notes` source, test them there, and reinstall; do not maintain two independent implementations.

For scheduled generation, verify `codex --version` and `codex login status` as the scheduler's operating-system user. The interactive shell and scheduler can have different `PATH` values; `notesctl schedule install` resolves the generator and records the current `PATH` only in the ignored local wrapper.

Set `EMBEDDED_NOTES_SITE_ROOT` locally, or run Codex from inside the Hugo repository. No machine-specific absolute path is stored in the Skill.

For the current site, use `content/embedded/embedded-study`, YAML front matter, `hugo --gc --minify`, the GitHub `main` branch, and Cloudflare Pages as the deployment consumer.

## Local setup

1. Install Python 3.11+, Git, Hugo Extended, and Codex CLI.
2. Clone the Hugo repository and set `EMBEDDED_NOTES_SITE_ROOT` to that checkout.
3. Run `python tools/embedded-notes/scripts/install_skill.py --update` from that checkout.
4. Run `codex --version`, `codex login status`, `git fetch origin`, and `hugo --gc --minify` as the user that will own the scheduled task.
5. Initialize the repository configuration only once, commit `.embedded-notes/config.toml`, `.embedded-notes/.gitignore`, and `.embedded-notes/manifest.json`, then perform a non-publishing single-note test before enabling auto-push.

Install the Windows scheduled task after the configured remote branch is correct and a manual single-note build has succeeded. The local tool continues to sync with GitHub, build Hugo, and push notes; Cloudflare Pages remains the deployment consumer.
