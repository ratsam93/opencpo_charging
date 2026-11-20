# opencpo.io test results (2026-11-19)

Tested in headless Chromium at 1280px and 390px plus raw HTTP checks.

## Works (TESTED)
- `/` and `/skins` load; `/skins.html` redirects (308) to `/skins`.
- All 17 skin screenshots return 200 and render (lazy-loaded).
- No horizontal overflow at 390px; mobile nav toggle present.
- Every `#anchor` link has a target. Title, description, Open Graph, canonical, JSON-LD present.
- `robots.txt`, `sitemap.xml` (lastmod 2026-04-10), `www.opencpo.io` all respond.

## Broken
1. **"Request Demo Access" form does nothing.** The inline script has literal newlines inside
   quoted strings, a JavaScript SyntaxError, so the submit handler never attaches. The form has no
   `action`, so a click reloads the page with name/email in the URL. Even if fixed, it only opens a
   `mailto:`. Fix: use `\n` escapes or template literals; better, post to a form service. (TESTED: parse
   error reproduced with `node --check`; the form was deliberately not submitted on the live site.)
2. **A personal email address is hardcoded in that script** while the visible contact link uses
   Cloudflare email protection.

## Smaller problems
- No 404 page: any URL (including `/docs`, `/install.sh`) returns the homepage with HTTP 200.
- 17 of 18 images on `/skins` have no `alt` text.
- Only `nosniff` and `referrer-policy` headers; no HSTS, CSP or X-Frame-Options.
- Lightbox `<img>` has an empty `src`.
- Content claims: see [claims-vs-reality.md](claims-vs-reality.md).

## Not tested
`demo.opencpo.io` (the "full CPO guide" link), Discord and GitHub links, Google Fonts: hosts were not
reachable from the sandbox. The site's source is in none of the audited repos.
