# Embedded Notes

`embedded-notes` turns embedded-systems material into Hugo Markdown, then
synchronizes, validates, builds, commits, and pushes the result. The Codex
Skill is a thin agent adapter; the deterministic core is ordinary Python and
can also be called by other agents or directly from a shell.

## Architecture

```text
Codex or another agent
  -> one request JSON plus one draft JSON per requested note
  -> notesctl validation and rendering
  -> Git synchronization
  -> Hugo build
  -> scoped commit and push
  -> optional external publish command
```

Site-specific state belongs in the Hugo repository under `.embedded-notes/`.
The Skill contains no machine-specific paths, credentials, or Hugo content.

The generation boundary is strict:

- `single` means `count = 1` and exactly one draft.
- `batch` requires an explicit count of at least two and exactly that many
  drafts.
- A scheduled multi-topic plan loops over the same single-note pipeline once
  per topic.

## Install

After cloning the Hugo repository on the local Windows machine:

```text
python tools/embedded-notes/scripts/install_skill.py --update
```

Requirements are Python 3.11+, Git, Hugo Extended, and an authenticated Codex
CLI when AI generation or scheduling is used. Run Codex inside the Hugo
repository, pass `--site-root`, or set `EMBEDDED_NOTES_SITE_ROOT` locally.

The local pipeline builds Hugo and pushes the configured GitHub branch.
Cloudflare Pages continues to build and host the site from that branch.

## Codex Examples

Each of these is a single-note request unless a count is explicit:

```text
Use $embedded-notes to create one note about STM32 DMA double buffering.
Use $embedded-notes to record the embedded topic from our current conversation as one note.
Use $embedded-notes to create one note from ./docs/timer.md.
Use $embedded-notes to create one note from https://example.com/reference.
Use $embedded-notes to create exactly three notes about SPI, I2C, and UART.
```

The first four requests must never invoke an unrelated legacy batch workflow.

## Core Commands

```text
python tools/embedded-notes/scripts/notesctl.py status --site-root <site>
python tools/embedded-notes/scripts/notesctl.py sync --site-root <site>
python tools/embedded-notes/scripts/notesctl.py create --site-root <site> --request <request.json>
python tools/embedded-notes/scripts/notesctl.py build --site-root <site>
python tools/embedded-notes/scripts/notesctl.py plan run --site-root <site> --plan-id <plan>
python tools/embedded-notes/scripts/notesctl.py schedule install --site-root <site> --plan-id <plan>
```

Every mutating workflow synchronizes first. Cloud fast-forwards preserve
non-conflicting local changes; conflicting changes stop the operation. Draft
transactions and stable request IDs make retries idempotent.

## Other Agents

`SKILL.md`, `$embedded-notes`, and `agents/openai.yaml` are the Codex adapter.
The request format, `notesctl.py`, Git/Hugo pipeline, and scheduler are not
Codex-specific. Another agent needs only a thin adapter that follows the same
single/batch contract, emits the documented JSON drafts, and invokes
`notesctl.py`. Scheduled generation can replace `[generator].command` with a
different non-interactive agent CLI without changing the core pipeline.

## Verification

```text
python -m unittest discover -s tools/embedded-notes/tests
```

The repository CI runs the same suite on Windows. See the detailed
request, source, synchronization, Hugo, and scheduling contracts in
`references/`.
