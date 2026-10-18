# Synchronization Policy

The Hugo Git remote is the cloud content source. The publish destination is separate and is never used as the source of truth.

Every mutating operation first runs `notesctl.py sync`. The tool fetches the configured remote and compares the local branch with its remote-tracking branch.

- Equal commits: continue.
- Remote ahead: fast-forward after backing up local managed changes.
- Local ahead: keep local commits and push after the new note is ready.
- Diverged: back up local changes. Automatic cloud-wins reset is allowed only when `repository_is_dedicated = true`; otherwise stop before changing the repository.
- Any local change outside the configured content and `.embedded-notes` paths is preserved and causes a safe stop if it would make cloud-wins ambiguous.
- A failed push never force-pushes. The draft and local commit remain available for a later fetch/retry.

Backups are written below `.embedded-notes/backups/<timestamp>/` and include Git patches plus copies of the managed content, configuration, manifest, plans, and pending transactions. Backup and transaction directories are ignored by Git.

The local lock is an atomic file created below `.embedded-notes/locks/`. A second process exits instead of interleaving writes. Git push rejection is the cross-machine concurrency boundary: the rejected process must sync again before retrying.

Each create request has an ignored transaction file until build, commit, push, and optional publish have all completed. Reusing the same `request_id` resumes only the unfinished stages and does not create another note. A fully completed request returns `already-applied` without publishing again.
