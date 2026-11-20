# Component repositories

`docker-compose.yml` builds each service from a folder next to it. These folders are cloned by
`setup.sh` (and are git-ignored here). Upstream project: https://github.com/opencpo

| Folder | Upstream | Fork used for fixes |
|---|---|---|
| `opencpo-core` | opencpo/opencpo-core | not yet forked |
| `opencpo-admin` | opencpo/opencpo-admin | ratsam93/opencpo-admin_charger |
| `opencpo-charge-app` | opencpo/opencpo-charge-app | ratsam93/opencpo-charge-app |
| `opencpo-tester` | opencpo/opencpo-tester | ratsam93/opencpo-tester |
| `opencpo-charger-farm` | opencpo/opencpo-charger-farm | ratsam93/opencpo-charger-farm |
| `opencpo-bastion` | opencpo/opencpo-bastion (not in compose) | ratsam93/opencpo-bastion |

Audited commits: core `b2d5ee8`, admin `22bbc51`, charge-app `9f5c2e4`, tester `479e91f`,
charger-farm `f2a5daa`, bastion `1c07c77`. See [audit/README.md](audit/README.md).

To test your forks on a server, clone each fork into the folder name in the first column.
