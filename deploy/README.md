# Deploying the site

The site is static: everything runs in the visitor's browser. The host only serves files.

```
GitHub release vX  --(workflow "site")-->  site-vX.zip + .sha256 attached to the release
protect-sync  --(public API, every 15 min)-->  /opt/devoprotect-site/www/releases/vX, then current -> releases/vX
protect-site (nginx)  <--  the Cloudflare tunnel  <--  visitors
```

## Once

1. Folder: `/opt/devoprotect-site/www`, owned by uid 10101 (written by protect-sync).
2. The tunnel: in Cloudflare, add the public hostname `protect.devoltz.party` to the tunnel of the existing
   `devo-site` stack, pointing at `http://protect-site:80`. The containers join that stack's Docker network
   (`devo-site`), so the same tunnel reaches them. With a tunnel of its own instead, add a `cloudflared` service.
3. `docker compose up -d` in this folder (or the same file as a stack in your Docker manager).

## Each release

Publish the GitHub release; the `site` workflow attaches `site-<tag>.zip`. protect-sync puts it in place within 15
minutes (`docker logs protect-sync`). To go back: point `current` at an older folder in `releases/`.

## What the server keeps

Nothing about visitors: nginx has no access log, there are no cookies and no metrics. Every answer is
`Cache-Control: no-cache`, and the page keeps its own offline copy (`sw.js`).
