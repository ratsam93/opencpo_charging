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

Built-in defaults (edit with `.deploy/repos.conf`, one `dir|git-url|branch|services` line per repo):

| Folder | Repo | Branch | Rebuilds |
|---|---|---|---|
| `.` (this repo) | ratsam93/opencpo_charging | `claude/great-newton-0flk8g` | whole stack, only if `docker-compose*.yml` / `.env.example` changed |
| `opencpo-admin` | ratsam93/opencpo-admin_charger | `claude/audit-fixes` | `cpo-admin` |
| `opencpo-charge-app` | ratsam93/opencpo-charge-app | `claude/audit-fixes` | `charge-app` |
| `opencpo-tester` | ratsam93/opencpo-tester | `claude/audit-fixes` | `compliance-tester` (build only) |
| `opencpo-charger-farm` | ratsam93/opencpo-charger-farm | `claude/audit-fixes` | `charger-farm` |

`opencpo-core` is **not** auto-deployed by default because the only copy is the upstream
project. Once you have your own fork, add a line to `.deploy/repos.conf`:
`opencpo-core|https://github.com/<you>/opencpo-core.git|<branch>|ocpp-core`
(a `repos.conf` replaces the defaults, so copy the other lines into it too).

## One-time server setup (as the `opencpo` user unless noted)

1. **DNS.** Point two A records at the server: `charger1.techbeyondsolution.com` (driver app)
   and `admin.charger1.techbeyondsolution.com` (admin dashboard).
2. **Stack already running** from `~/opencpo_charging` with `.env` (mode 600) and, optionally,
   `docker-compose.override.yml` binding every port to `127.0.0.1`.
3. **Shared network for the reverse proxy.** The proxy (Caddy) runs in another Docker project,
   so it cannot use `127.0.0.1`. Add to `.env`:
   `COMPOSE_FILE=docker-compose.yml:docker-compose.override.yml:docker-compose.edge.yml`
   (drop the override file from the list if you don't use one), then
   `docker compose up -d` and attach the proxy once:
   `docker network connect opencpo_edge <caddy-container-name>`.
   *This attachment is lost if the proxy container is ever recreated; re-run the command, or add the
   `opencpo_edge` network to the proxy's own compose file.*
4. **Reverse proxy.** Add the blocks from `deploy/caddy/opencpo.caddy` to the Caddyfile
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
