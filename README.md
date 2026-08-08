# Minecraft: Creark

This is my personal modpack for my dedicated Minecraft Server. Everything is served within my personal network.

# How to join

## Prerequisite

- Tailscale: [Download | Tailscale](https://tailscale.com/download)
- Have a good enough relationship with Repo Owner :3

## Setup

- Login to Taiscale with the following credentials
  - Username: `blieu.dummy@gmail.com`
  - Password and 2FA Code: Ask me for this
- Choose `hao.lieu.02@gmail.com`'s tailnet
- Proceed to [this](https://fileblieu.whydah-dab.ts.net/s/JkmJJGSzG47PQgL) link for more information

# Build & release workflow

This repo is the source of truth for the modpack. Modpack data (manifest, config, `local-mods/`, `servers.dat`) lives in the repo and is built into distributable artifacts by CI on every merge to `main`.

## Updating mods (maintainer)

1. Add/remove/update mods as usual in the SKLauncher instance on your machine.
2. Run `uv run sync_instance.py` to pull the manifest, `config/`, `servers.dat`, and any non-Modrinth mod jars from the SKLauncher instance into the repo (see the script's docstring for `--instance-dir` / `SK_INSTANCE_DIR` options).
3. Review the diff, commit, and open a PR.
4. Merging to `main` automatically triggers the CI workflow (`.github/workflows/release.yml`), which builds all artifacts (`make build-all`) and publishes them as a new GitHub Release.

If a mod should be excluded from the dedicated server build (e.g. client-only mods like freecam), add its slug/id to `server-excludes.txt`. Remove it from that file to have it included again.

## Consuming a release (friends/players)

Releases are published on the repo's [GitHub Releases page](../../releases). Each release has three assets:

- **`Creark-<timestamp>.mrpack`** — the full client modpack. Import it into a launcher that supports the `.mrpack` format (Modrinth App, Prism Launcher, etc.) to get mods, config, and server settings in one go.
- **`Creark-Server-<timestamp>.mrpack`** — the server-side modpack, same as the client build but with client-only mods (see `server-excludes.txt`) dropped. Use this to set up or update a dedicated server.
- **`Creark-Mods-Only-<version>.zip`** — just the mod jars, flattened into a zip. Drop these straight into an existing server or client's `mods/` folder to update mods in place without touching world data or config.

Grab whichever asset matches what you're doing from the latest release; you generally don't need to build anything locally.

## Running the dedicated server

There are two compose files:

- `docker-compose.dev.yml` — local dev. Uses `itzg/minecraft-server:java21` directly with `modpack.mrpack` bind-mounted from the repo root. `make run` / `make run-watch` / `make log` / `make stop` all target this.
- `docker-compose.prod.yml` — prod. Uses a custom image (built from the repo's `Dockerfile`, which bakes the built modpack in) instead of a bind mount, so the VM doesn't depend on local files, and world data lives in a named `data` volume so it survives image updates. `make prod-up` / `make prod-log` / `make prod-stop` run this locally for testing.

Operational settings for prod (`OPS`, `MEMORY`, `LEVEL`, difficulty, RCON commands, etc.) are overridable per-deploy without rebuilding the image: copy `.env.example` to `.env` and edit it — Compose loads `.env` and substitutes `${VAR}` automatically. Anything left unset falls back to the same default baked into the `Dockerfile`.

### Publishing the server image (CI)

On every push to `main`, `.github/workflows/deploy.yml` builds the client modpack, bakes it into the `Dockerfile` image, and pushes `ghcr.io/corvolieu/mc-creark-modpack:latest` (plus a `:sha-<short-sha>` tag for rollback/debugging) to GitHub Container Registry using the workflow's own `GITHUB_TOKEN` — no extra secrets needed on the CI side. This is separate from `release.yml`, which publishes `.mrpack` files for players; the two can run independently off the same push.

**GHCR package visibility:** packages published this way default to **private**, scoped to the repo. Watchtower on the prod VM needs pull access, so either:

- make the `mc-creark-modpack` package public in its GitHub package settings ([repo] → Packages → package → Package settings), or
- keep it private and have the VM's Docker authenticate: `docker login ghcr.io -u <github-username> -p <PAT>` using a personal access token with `read:packages` scope, run once (or stored in Watchtower's config) so it can pull on every poll.

Don't assume the package is publicly pullable without checking — confirm in the repo's Packages tab after the first CI run.
