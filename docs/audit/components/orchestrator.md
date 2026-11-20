# Orchestrator (this repo)

Fixed on branch `claude/great-newton-0flk8g` (commits a5ff294, bcc6443, 54f86cc). Verified by running
`configure.py --auto`, `docker compose config`, and sourcing `.env` in bash.

## Fixed
- `POSTGRES_PASSWORD` now feeds postgres and core (compose read an unset `PG_PASSWORD`).
- `SECRET_KEY` and `MANAGEMENT_API_KEY` required; `configure.py` generates both; no `CHANGE_ME` fallbacks.
- `.env` and `.env.bak` mode 600; all values single-quoted so bash and compose agree (default `ORG_NAME=My CPO` broke `source .env`).
- Postgres and Redis bound to 127.0.0.1; dead tester `DEFAULT_WS_URL` removed.
- `update.sh` / `db-utils.sh` no longer fall back to password `ocpp`; `version.txt` aligned; stray file removed.

## Still open
- Redis has no password; tester and farm start by default; no container hardening/resource limits.
- `docker.sock` mounted into core (read-only still grants API access).
- Installers pipe `curl | bash` with no checksums; `update.sh` extracts a tarball with no verification.
- `docker-compose.yml` has no `db/migrations` source: `setup.sh` loads `schema.sql` itself, bare `compose up` does not.
- Bastion absent from compose; charge-app and farm have no healthcheck.
- No CI (shellcheck, `docker compose config`, a `configure.py` round-trip test).
- `CHANGELOG.md` (v1.0.0) and `SECURITY.md` (1.x) do not match the 0.6.x versions.
