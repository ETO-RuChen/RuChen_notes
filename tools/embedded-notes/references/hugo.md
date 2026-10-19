# Hugo Configuration

Initialize a Hugo site with:

```text
python scripts/notesctl.py init --site-root <hugo-site> --content-dir content/embedded/embedded-study
```

The generated `.embedded-notes/config.toml` is intentionally site-specific. It does not contain secrets.

```toml
[site]
content_dir = "content/embedded/embedded-study"
front_matter = "yaml"
filename_style = "date-slug"
default_draft = false
default_tags = ["嵌入式", "EmbeddedStudy"]
default_categories = ["嵌入式"]
default_series = ["EmbeddedStudy"]
default_featureimage = ""
default_summary = ""
include_lastmod = true

[git]
remote = "origin"
branch = "main"
require_remote = true
cloud_wins_on_divergence = true
repository_is_dedicated = false
auto_commit = true
auto_push = true

[hugo]
enabled = true
command = ["hugo", "--gc", "--minify"]

[publish]
enabled = false
command = []
```

`publish.command` is an argument array, not a shell string. For the current repository, pushing the configured Git remote is the publish step and Cloudflare Pages runs `hugo --gc --minify` from `main`. A separate command is only needed if the deployment target changes. Secrets belong in SSH agents, environment variables, or the operating system credential store.
