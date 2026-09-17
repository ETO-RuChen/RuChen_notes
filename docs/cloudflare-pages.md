# Cloudflare Pages deployment

Connect the GitHub repository `ETO-RuChen/RuChen_notes` to Cloudflare Pages with
these production settings:

| Setting | Value |
| --- | --- |
| Production branch | `main` |
| Build command | `hugo --gc --minify` |
| Build output directory | `public` |
| Environment variable | `HUGO_VERSION=0.151.0` |
| Custom domain | `195481.xyz` |

Before enabling production deployment, create a preview deployment and verify
the Blowfish submodule, generated EmbeddedStudy page, asset paths, navigation,
and custom-domain redirects. Existing comment-component warnings are known and
do not block this pipeline unless Hugo exits with a non-zero status.
