# Cloudflare Pages deployment

Connect the GitHub repository `ETO-RuChen/RuChen_notes` to Cloudflare Pages with
these production settings:

| Setting | Value |
| --- | --- |
| Production branch | `main` |
| Build command | `hugo --gc --minify` |
| Build output directory | `public` |
| Environment variable | `HUGO_VERSION=0.151.0` |
| Custom domain | `blog.195481.xyz` |

Before enabling production deployment, create a preview deployment and verify
the Blowfish submodule, generated EmbeddedStudy page, asset paths, navigation,
and custom-domain redirects. Existing comment-component warnings are known and
do not block this pipeline unless Hugo exits with a non-zero status.


## Migration to blog.195481.xyz

The production Hugo baseURL is `https://blog.195481.xyz/`.

1. In Cloudflare Workers & Pages, open this site's existing Pages project.
2. Under Custom domains, add `blog.195481.xyz` to the same project.
3. Confirm the suggested DNS record. If DNS is managed elsewhere, create a
   CNAME named `blog` pointing to the actual production `<project>.pages.dev`
   hostname shown by this project. Associate the custom domain in Pages first;
   creating only a DNS record is insufficient.
4. Wait until the custom domain is Active and HTTPS works.
5. Push the domain configuration change to `main` to trigger the production
   build. Check the homepage, an article, static assets, and `/sitemap.xml`.
   If Cloudflare has a `HUGO_BASEURL` environment variable or an explicit
   `--baseURL` build argument, update it to `https://blog.195481.xyz/` too.
6. If the old apex should continue forwarding to the blog, configure an
   optional Cloudflare redirect rule matching hostname `195481.xyz` with
   dynamic target `concat("https://blog.195481.xyz", http.request.uri.path)`,
   status 301, and Preserve query string enabled. Keep the apex DNS record
   proxied for this rule. Skip this if the apex will serve another website.

Do not add an unconditional path-only redirect to the Pages `_redirects` file:
it would also match requests to the new domain.
