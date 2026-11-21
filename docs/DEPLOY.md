# Auto-deploy from GitHub

A systemd timer on the server runs `scripts/deploy.sh` every minute. When a watched
branch on GitHub has a new commit, the script pulls it, rebuilds only the affected
Docker Compose services, waits for their health check, and **rolls back** if the check
fails. Nothing on the server accepts logins from GitHub and no GitHub secrets are needed
(the repos are public, so the server only reads).

```
you / Claude push  ->  GitHub branch  ->  server polls (60 s)  ->  build  ->  health check
                                                                      \-> failed? roll back, remember the bad commit
```

Tested offline with `scripts/test-deploy.sh` (30 checks: deploy, no-op, rollback, bad-commit
memory, pause, dirty tree, self-update, lock). It has **not** yet run against a real server.

## What it watches

This repository is the only repo to watch: the script follows one branch of `opencpo_charging`
(built-in default: `claude/great-newton-0flk8g`; change the branch in `.deploy/repos.conf` or in
`DEFAULT_REPOS` to `main` once the work is merged). In `auto` mode it looks at **which folders changed**
and rebuilds only those services:

| Changed path | Rebuilds |
|---|---|
| `opencpo-core/` | `ocpp-core` |
| `opencpo-admin/` | `cpo-admin` |
| `opencpo-charge-app/` | `charge-app` |
| `opencpo-charger-farm/` | `charger-farm` |
| `opencpo-tester/` | `compliance-tester` (build only) |
| `docker-compose*.yml`, `.env.example` | the whole stack (`up -d`) |
| `docs/`, `scripts/`, `deploy/`, `opencpo-bastion/`, anything else | nothing (pulled only) |

Separate repos are still supported: list them in `.deploy/repos.conf` (`dir|git-url|branch|services`).

## Moving a server from the old separate repos to the single repo (once)

Run as the `opencpo` user in `~/opencpo_charging`. Your `.env`, `docker-compose.override.yml` and `edge/` are untouched.
```bash
scripts/deploy.sh --status                       # note what is deployed now
touch .deploy/PAUSE                              # stop auto-deploy while migrating
git fetch origin claude/great-newton-0flk8g
rm -rf opencpo-core opencpo-admin opencpo-charge-app opencpo-tester opencpo-charger-farm   # old clones, no local changes
git checkout -B claude/great-newton-0flk8g origin/claude/great-newton-0flk8g
docker compose config -q && docker compose up -d --build
rm -f .deploy/repos.conf                         # use the built-in single-repo default
rm .deploy/PAUSE
```
Check `docker compose ps` and `scripts/deploy.sh --status` afterwards.

Core now requires the management key on its admin, charger, session and event routes and signs-checks its payment
webhook. The admin and charge app send the key, so deploy them together (one push does). For an existing `.env`, add a
webhook secret once: `echo "PAYMENT_WEBHOOK_SECRET='$(openssl rand -hex 32)'" >> .env` (see `opencpo-core/docs/payments.md`). The component folders now come from this
repository; the `pki-data` volume (certificate authority) is not affected.

## Public access: two layouts

**A. Dedicated Caddy container (what the first deployment uses).** A separate Caddy container,
defined in the git-ignored `edge/` folder and `docker-compose.override.yml`, serves
`https://charger1.techbeyondsolution.com:8443` with its own Let's Encrypt certificate
(DNS-01 challenge via Cloudflare) and HTTP basic auth, proxying only `cpo-admin`. It does not
touch any other proxy on the host, and `ufw` allows 8443/tcp. Keep the Cloudflare token in `edge/`
(never in git). Core and the charge app are not exposed.

**B. Join an existing proxy.** Use `docker-compose.edge.yml` (below) and `deploy/caddy/opencpo.caddy`
if an existing Caddy already owns ports 80/443 and you are happy to edit its config.

Either way, `scripts/deploy.sh` is independent of the proxy: it only rebuilds services and checks
their health on `127.0.0.1`.

## Safe defaults in `docker-compose.yml`

- Every published port binds to `127.0.0.1` (`BIND_ADDR`, default `127.0.0.1`). Set `BIND_ADDR=0.0.0.0`
  in `.env` only if you want the services reachable from the network, and remember Docker bypasses `ufw`.
- Core does **not** mount the Docker socket or the repository (which contains `.env`). It only gets
  `./scripts` read-only (for the backup helper) and the backup volume. The admin "update" button is
  therefore disabled; to enable it deliberately use `docker-compose.updater.yml`
  (read the warning at its top). Prefer `scripts/deploy.sh`.
- Core's certificate authority (root CA, sub-CAs, private keys) lives in the `pki-data` volume at
  `/app/data/pki`. Without it the CA is regenerated every time the core container is recreated and every
  certificate issued before becomes orphaned. **If your `docker-compose.override.yml` replaces core's
  `volumes` (for example with `!override`), keep `pki-data:/app/data/pki` and `backup-data:/app/backups`
  in the list.**
- Core's own migrations do not work. After the first `docker compose up`, run `scripts/load-schema.sh`
  once (it is idempotent and restarts core). `setup.sh` does the same on a first install.

## One-time server setup (as the `opencpo` user unless noted)

1. **DNS.** Point two A records at the server: `charger1.techbeyondsolution.com` (driver app)
   and `admin.charger1.techbeyondsolution.com` (admin dashboard).
2. **Stack already running** from `~/opencpo_charging` with `.env` (mode 600), the schema loaded
   (`scripts/load-schema.sh`), and optionally a git-ignored `docker-compose.override.yml`.
3. **(Layout B only) Shared network for the reverse proxy.** The proxy (Caddy) runs in another Docker project,
   so it cannot use `127.0.0.1`. Add to `.env`:
   `COMPOSE_FILE=docker-compose.yml:docker-compose.override.yml:docker-compose.edge.yml`
   (drop the override file from the list if you don't use one), then
   `docker compose up -d` and attach the proxy once:
   `docker network connect opencpo_edge <caddy-container-name>`.
   *This attachment is lost if the proxy container is ever recreated; re-run the command, or add the
   `opencpo_edge` network to the proxy's own compose file.*
4. **(Layout B only) Reverse proxy.** Add the blocks from `deploy/caddy/opencpo.caddy` to the Caddyfile
   (back it up first, `caddy validate`, then a graceful `caddy reload`, never a restart).
   Both sites sit behind `basic_auth` while testing, and the charge app's block strips
   `X-Client-Cert-Serial`. Do not proxy `ocpp-core`.
5. **Install the timer (as root):** `sudo scripts/install-deploy-timer.sh --user opencpo`

Check: `scripts/deploy.sh --status`, `systemctl list-timers opencpo-deploy.timer`, `tail -f deploy.log`.

## Day to day

| Want to | Do |
|---|---|
| See what is deployed | `scripts/deploy.sh --status` |
| Stop deploying for a while | `touch .deploy/PAUSE` (delete the file to resume) |
| Deploy now instead of waiting | `scripts/deploy.sh` |
| Retry a commit that failed its health check | `scripts/deploy.sh --force` |
| Read what happened | `deploy.log` |
| Remove the timer | `sudo scripts/install-deploy-timer.sh --uninstall` |

## Rules it follows

- Never touches `.env`, `docker-compose.override.yml`, or any other Docker project on the host.
- A checkout with local changes to tracked files is **not** overwritten (it logs an error).
- A commit that fails its health check is rolled back and not retried until the branch moves on.
- One run at a time (`flock`); builds run at low CPU/IO priority.
- A missing network or deleted branch is a warning, not an outage.

## Limits and cautions

- **Anyone who can push to a watched branch can run code on your server.** Turn on two-factor
  authentication for the GitHub account and do not add collaborators lightly.
- **Rollback restores code, not data.** Database changes are not undone. Schema loading is not
  part of the deploy (core's migrations are broken upstream; see `docs/audit/components/core.md`).
- Health checks: core `/health/ready`, admin `/health`, charge app `/health`, farm `/health`.
  The tester is a CLI that exits when no charger connects, so only its build is checked.
- `python configure.py` rewrites `.env` and drops `COMPOSE_PROJECT_NAME` and `COMPOSE_FILE`;
  re-add them afterwards.
- Keep `basic_auth` on both sites until core's open endpoints are fixed.
