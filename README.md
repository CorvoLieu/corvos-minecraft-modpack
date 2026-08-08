# Minecraft: Creark

My personal modpack for my dedicated Minecraft Server, served on my personal network.

# How to join

## Prerequisite

- Tailscale: [Download | Tailscale](https://tailscale.com/download)
- Have a good enough relationship with Repo Owner :3

## Setup

- Login to Tailscale with:
  - Username: `blieu.dummy@gmail.com`
  - Password and 2FA Code: Ask me for this
- Choose `hao.lieu.02@gmail.com`'s tailnet
- See [this link](https://fileblieu.whydah-dab.ts.net/s/JkmJJGSzG47PQgL) for further info

# Build & release workflow

This repo is the source of truth for the modpack. Modpack data (manifest, `config/`, `local-mods/`, `servers.dat`) lives here and CI builds it into distributable artifacts on every merge to `main`.

## Updating mods (maintainer)

1. Add/remove/update mods in the SKLauncher instance on your machine.
2. `uv run sync_instance.py` — pulls the manifest, `config/`, `servers.dat`, and any non-Modrinth mod jars from SKLauncher into the repo (see the script's docstring for `--instance-dir` / `SK_INSTANCE_DIR`).
3. Review the diff, commit, open a PR.
4. Merge to `main` triggers `.github/workflows/release.yml`, which runs `make build-all` and publishes the results as a new GitHub Release.

To exclude a mod from the dedicated server build (e.g. client-only mods like freecam), add its slug/id to `server-excludes.txt`; remove it to re-include.

## Contributing a mod

Same mechanics as above, as a PR workflow:

1. Add/update the mod in your own local SKLauncher instance.
2. `uv run sync_instance.py --instance-dir <path>` (or set `SK_INSTANCE_DIR`). Modrinth-sourced mods are referenced by hash/URL in the manifest, not committed as jars; non-Modrinth jars land in `local-mods/`.
3. Build and test locally before opening a PR: `make build-client` (or `make build-all`), then `make run` to spin up `docker-compose.dev.yml` and confirm the mod loads and works.
4. Review your diff — expect a changed entry in `manifest/creark.json`, possibly a new jar under `local-mods/`. Add client-only mods to `server-excludes.txt`.
5. Commit on a branch, open a PR.
6. After merge, `release.yml` and `deploy.yml` publish new release assets and roll out to prod via Watchtower automatically — nothing further needed.

### Pre-commit sync check

- `.githooks/pre-commit` (logic in `scripts/hooks/check-sync.sh`) re-runs `sync_instance.py` and blocks any commit touching `manifest/`, `config/`, `local-mods/`, or `servers.dat` if the staged content disagrees with what your local SKLauncher instance would produce (mods changed but not synced, or synced but not `git add`ed).
- Skips with a warning (not a failure) if `SK_INSTANCE_DIR` isn't configured, so it never blocks unrelated changes (docs, CI, `Dockerfile`, etc.).
- Installed automatically: every `make` target depends on `install-hooks`, which symlinks it into `.git/hooks/` the first time you run `make` after cloning. Nothing to run by hand.
- **Convenience guard, not a hard guarantee** — hooks live outside version control, so this only protects contributors who've run `make` at least once, and can be bypassed with `git commit --no-verify`. No CI-side re-enforcement of the sync check yet.

## Consuming a release (friends/players)

Grab the matching asset from the [latest release](../../releases) — no local build needed:

- **`Creark-<timestamp>.mrpack`** — full client modpack. Import into any `.mrpack`-compatible launcher (Modrinth App, Prism Launcher, etc.) for mods, config, and server settings in one go.
- **`Creark-Server-<timestamp>.mrpack`** — server-side build, same as client but with `server-excludes.txt` mods dropped. Use to set up/update the dedicated server.
- **`Creark-Mods-Only-<version>.zip`** — just the mod jars, flattened. Drop into an existing server/client `mods/` folder to update in place without touching world data or config.

## Running the dedicated server

Two compose files:

- `docker-compose.dev.yml` — local dev. `itzg/minecraft-server:java21` with `modpack.mrpack` bind-mounted from the repo root. Targeted by `make run` / `make run-watch` / `make log` / `make stop`.
- `docker-compose.prod.yml` — prod. Custom image (built from the repo `Dockerfile`, which bakes in the built modpack) instead of a bind mount, so the VM has no local-file dependency; world data lives in a named `data` volume so it survives image updates. Targeted locally by `make prod-up` / `make prod-log` / `make prod-stop`.

Prod settings (`OPS`, `MEMORY`, `LEVEL`, difficulty, RCON commands, etc.) are overridable per-deploy without rebuilding: copy `.env.example` to `.env` and edit — Compose loads it and substitutes `${VAR}` automatically. Unset vars fall back to the `Dockerfile` defaults.

### Publishing the server image (CI)

On every push to `main`, `.github/workflows/deploy.yml` builds the client modpack, bakes it into the `Dockerfile` image, and pushes `ghcr.io/corvolieu/mc-creark-modpack:latest` (plus `:sha-<short-sha>` for rollback/debugging) to GHCR using the workflow's own `GITHUB_TOKEN` — no extra secrets needed. Independent of `release.yml` (which publishes `.mrpack` files for players); both can run off the same push.

**GHCR package visibility:** packages default to **private**, scoped to the repo. Watchtower on the prod VM needs pull access — either:

- make the `mc-creark-modpack` package public ([repo] → Packages → package → Package settings), or
- keep it private and authenticate the VM's Docker: `docker login ghcr.io -u <github-username> -p <PAT>` (PAT needs `read:packages`), run once or stored in Watchtower's config.

Confirm actual visibility in the repo's Packages tab after the first CI run — don't assume.

### Auto-deploy on the prod VM (Watchtower)

`docker-compose.prod.yml` includes a `watchtower` service that:

- Polls GHCR every 5 minutes (`WATCHTOWER_POLL_INTERVAL`, override in `.env`); on a new `:latest` digest, pulls and recreates the `mc-s3` container. This is the entire auto-deploy-on-merge mechanism — no SSH push step.
- Is scoped via `--label-enable`/`WATCHTOWER_LABEL_ENABLE` plus the `com.centurylinklabs.watchtower.enable=true` label on `mc-s3`, so it only touches the Minecraft server container.
- Runs with `WATCHTOWER_CLEANUP=true`, pruning the superseded image after each update.
- Doesn't affect world data, which lives in the named `data` volume and survives container recreation.

One-time manual setup on the VM:

1. If the GHCR package is private: `docker login ghcr.io -u <github-username> -p <PAT>` once, so the host Docker daemon has pull credentials — Watchtower reuses that auth via the mounted `/var/run/docker.sock` rather than taking its own registry credentials.
2. `docker compose -f docker-compose.prod.yml up -d` once to start `mc-s3` and `watchtower`. From then on, every push to `main` that lands a new image is picked up automatically within one poll interval.
