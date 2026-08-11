# Minecraft: CreativeWorld - S4

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
- Download modpack (mrpack) or Mod-Only zip in this repo [releases](../../releases)
- See [this link](https://fileblieu.whydah-dab.ts.net/s/JkmJJGSzG47PQgL) for further info

# Build & release workflow

This repo is the source of truth for the modpack. Modpack data (manifest, `local-mods/`, `local-datapacks/`, `servers.dat`) lives here and CI builds it into distributable artifacts on every merge to `main`.

The modpack/instance name (`minecraft-modded` by default) is controlled by a single `PACK_NAME` value in `.env` (see `.env.example`) -- renaming the pack (manifest filename, world/level name, default SKLauncher instance name, pack display name, local image tag) means changing that one value, not editing code. If unset, everything falls back to `minecraft-modded` so existing setups keep working unchanged.

## Setting up your local instance (maintainer)

`pull_instance.py` populates a fresh SKLauncher instance directly from this repo's committed state (manifest, `local-mods/`, `local-datapacks/`, `config/`, `servers.dat`) — no need to wait for a published release. See its docstring (`uv run pull_instance.py --help` or the top of `pull_instance.py`) for full details; summary below.

1. Install [SKLauncher](https://next.skmedix.pl/) (4.0 beta; the repo's scripts target its `instances/` layout, not 3.2's `.minecraft`-based profiles).
2. Create a new, empty instance via SKLauncher's "New Instance" UI (any mod loader/version — `pull_instance.py` overwrites `minecraftVersion`/`loaderVersion` to match `manifest/pack.json`, currently Minecraft 1.21.1, NeoForge 21.1.247 at time of writing; the file, not this README, is the source of truth if that's changed). `pull_instance.py` can't safely create the instance registration itself (SKLauncher-internal fields like icon/groups/java args aren't reverse-engineered), so this manual step is still required.
3. Find the instance directory SKlauncher created (macOS default: `~/Library/Application Support/sklauncher/instances/<PACK_NAME>`, `minecraft-modded` unless you've set `PACK_NAME`/`INSTANCE_NAME`; Windows/Linux vary, no safe default — locate it via SKlauncher's instance settings). Copy `.env.example` to `.env` and set `SK_INSTANCE_DIR` to it (or pass `--instance-dir <path>` per invocation) — this is the same resolution `push_instance.py` uses.
4. `make pull` (or `uv run pull_instance.py`) — previews everything it would add/update/remove, then prompts to confirm before touching the instance (pass `--yes` to skip the prompt, e.g. `uv run pull_instance.py --yes`). This downloads/copies mods into `mods/`, datapacks into `datapacks/`, reconciles `config/`, and copies `servers.dat` and the manifest into place.
5. From here, follow "Updating mods (maintainer)" below for the day-to-day workflow — `push_instance.py` is already pointed at the same instance via the `SK_INSTANCE_DIR` you set in step 3.

If you'd rather bootstrap from a published build instead (e.g. no repo checkout yet), grab `Minecraft-modded-<version>.mrpack` (named after `PACK_NAME`, Title-cased, `Minecraft-modded` by default) from the [latest release](../../releases) and drag it onto the SKlauncher window to create the instance directly — then set `SK_INSTANCE_DIR` as in step 3 and skip `pull_instance.py`. Note this path won't populate `config/`, since `config/` bundling into the `.mrpack` is currently commented out in `build_mrpack.py`/`push_instance.py`.

## Updating mods (maintainer)

1. Add/remove/update mods or datapacks in the SKLauncher instance on your machine.
2. `make push` (or `uv run push_instance.py`) — pushes the manifest, `servers.dat`, and any non-Modrinth mod jars/datapack zips from SKLauncher into the repo (see the script's docstring for `--instance-dir` / `SK_INSTANCE_DIR`).
3. Review the diff, commit, open a PR.
4. Merge to `main` triggers `.github/workflows/release.yml`, which runs `make build-all` and publishes the results as a new GitHub Release — but the workflow fails if `versionNumber` wasn't bumped (see "Cutting a release" below).

To exclude a mod from the dedicated server build (e.g. client-only mods like freecam), add its slug/id to `server-excludes.txt`; remove it to re-include. Datapacks are world/server-side content, so this generally shouldn't apply to them, but the same mechanism works if one ever needs excluding.

### Cutting a release

Releases are tied to a deliberate version bump, not every push to `main`. `.github/workflows/release.yml` reads `modpackLink.versionNumber` from `manifest/<PACK_NAME>.json` (`manifest/minecraft-modded.json` by default) and tags the release `v<versionNumber>` (e.g. `v1.0.0`). To cut a release:

1. Bump `versionNumber` in `manifest/<PACK_NAME>.json` in your commit/PR to `main`.
2. Once merged, CI tags and publishes a GitHub Release for that version.
3. If a release for that version already exists (i.e. `versionNumber` wasn't bumped), the workflow's "Check for existing release" step fails the job rather than skipping — bump the version and re-push to retry. The manifest path defaults to `manifest/<PACK_NAME>.json`; override it by setting the `MANIFEST_FILE` repository/environment variable if you ever need to point at a different file. The `Minecraft-modded-<tag>` artifact filename prefix comes from the `PACK_NAME` repository/environment variable (Title-cased), independent of the local `.env`'s `PACK_NAME` — set both if you rename the pack and want CI's release names to match.

## Contributing a mod

Same mechanics as above, as a PR workflow:

1. Add/update the mod or datapack in your own local SKLauncher instance.
2. `uv run push_instance.py --instance-dir <path>` (or set `SK_INSTANCE_DIR`, then `make push`). Modrinth-sourced mods/datapacks are referenced by hash/URL in the manifest, not committed as files; non-Modrinth jars land in `local-mods/`, non-Modrinth datapack zips in `local-datapacks/`.
3. Build and test locally before opening a PR: `make build-client` (or `make build-all`) to produce `exports/client.mrpack`, then `make run` to spin up `docker-compose.dev.yml` and confirm the mod/datapack loads and works.
4. Review your diff — expect a changed entry in `manifest/<PACK_NAME>.json`, possibly a new jar under `local-mods/` or zip under `local-datapacks/`. Add client-only mods to `server-excludes.txt`.
5. Commit on a branch, open a PR.
6. After merge, `release.yml` and `deploy.yml` publish new release assets and roll out to prod via Watchtower automatically — nothing further needed.

### Pre-commit sync check

- `.githooks/pre-commit` (logic in `scripts/hooks/check-sync.sh`) re-runs `push_instance.py` and blocks any commit touching `manifest/`, `local-mods/`, `local-datapacks/`, or `servers.dat` if the staged content disagrees with what your local SKLauncher instance would produce (mods/datapacks changed but not synced, or synced but not `git add`ed).
- Skips with a warning (not a failure) if `SK_INSTANCE_DIR` isn't configured, so it never blocks unrelated changes (docs, CI, `Dockerfile`, etc.).
- Installed automatically: every `make` target depends on `install-hooks`, which symlinks it into `.git/hooks/` the first time you run `make` after cloning. Nothing to run by hand.
- **Convenience guard, not a hard guarantee** — hooks live outside version control, so this only protects contributors who've run `make` at least once, and can be bypassed with `git commit --no-verify`. No CI-side re-enforcement of the sync check yet.

## Consuming a release (friends/players)

Grab the matching asset from the [latest release](../../releases) — no local build needed (`Minecraft-modded` below is the Title-cased `PACK_NAME`, see "Cutting a release" above):

- **`Minecraft-modded-<version>.mrpack`** — full client modpack. Import into any `.mrpack`-compatible launcher (Modrinth App, Prism Launcher, etc.) for mods, and server settings in one go.
- **`Minecraft-modded-Server-<version>.mrpack`** — server-side build, same as client but with `server-excludes.txt` mods dropped. Use to set up/update the dedicated server.
- **`Minecraft-modded-Mods-Only-<version>.zip`** — just the mod jars, flattened. Drop into an existing server/client `mods/` folder to update in place without touching world data.

## Running the dedicated server

Two compose files:

- `docker-compose.dev.yml` — local dev. `itzg/minecraft-server:java21` with `exports/client.mrpack` bind-mounted (built by `make build-client`). Targeted by `make run` / `make run-watch` / `make log` / `make stop`.
- `docker-compose.prod.yml` — prod. Custom image (built from the repo `Dockerfile`, which bakes in the built modpack) instead of a bind mount, so the VM has no local-file dependency; world data lives in a named `data` volume so it survives image updates. Targeted locally by `make prod-up` / `make prod-log` / `make prod-stop`.

Prod settings (`OPS`, `MEMORY`, `LEVEL`, difficulty, RCON commands, etc.) are overridable per-deploy without rebuilding: copy `.env.example` to `.env` and edit — Compose loads it and substitutes `${VAR}` automatically. Unset vars fall back to the `Dockerfile` defaults. `docker-compose.dev.yml`'s `LEVEL` isn't a separate override — it derives directly from `PACK_NAME` (see above).

**`LEVEL` and datapacks:** manifest datapacks are baked into the built `.mrpack` at `overrides/<world>/datapacks/`, matching the world/level name Minecraft actually loads per-world datapacks from — this is `PACK_NAME` (`build_mrpack.py`'s `DATAPACK_WORLD_NAME`, `minecraft-modded` by default) to match the `LEVEL` default used everywhere else in this repo. If you ever override `LEVEL` in `docker-compose.prod.yml`/`stg.yml` to something other than `PACK_NAME`, datapacks will stop taking effect until `DATAPACK_WORLD_NAME`/`PACK_NAME` is updated to match.

### Publishing the server image (CI)

On every push to `main`, `.github/workflows/deploy.yml` builds the client modpack, bakes it into the `Dockerfile` image, and pushes `ghcr.io/<owner>/<repo>:latest` (plus `:sha-<short-sha>` for rollback/debugging) to GHCR using the workflow's own `GITHUB_TOKEN` — no extra secrets needed; the image name is derived from the GitHub repository, not `PACK_NAME` (default: `ghcr.io/corvolieu/corvos-minecraft-modpack`). Independent of `release.yml` (which publishes `.mrpack` files for players); both can run off the same push.

`docker-compose.stg.yml`/`docker-compose.prod.yml` pull that same image, via an `IMAGE_NAME` override in `.env` (defaults to `ghcr.io/corvolieu/corvos-minecraft-modpack`, see `.env.example`) — set it if you've forked the repo under a different name.

**GHCR package visibility:** packages default to **private**, scoped to the repo. Watchtower on the prod VM needs pull access — either:

- make the package public ([repo] → Packages → package → Package settings), or
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
