# Bakes the built client modpack into the itzg image for prod deploys, so
# the VM doesn't need a bind-mounted modpack.mrpack and Watchtower can just
# swap the whole image on update.
#
# Build the client modpack first (`make build-client`, or `make build-image`
# which does both steps), then:
#   docker build -t ghcr.io/<owner>/<repo>:latest .
FROM itzg/minecraft-server:java21

COPY exports/server.mrpack /modpack.mrpack

# Defaults mirroring docker-compose.dev.yml's environment block -- keep in
# sync. FORCE_REDOWNLOAD / FORCE_REINSTALL are intentionally omitted here:
# they'd force re-fetching the modpack from Modrinth on every container
# start, defeating the point of baking it into the image.
#
# Everything below except EULA/TYPE/MODRINTH_* is overridable per-deploy at
# runtime via docker-compose.prod.yml's environment block + a .env file (see
# .env.example) -- compose's `${VAR:-default}` substitution takes care of
# that, no envsubst step needed. These ENV values are just the fallback
# defaults baked into the image.
ENV EULA="TRUE" \
    TYPE="MODRINTH" \
    VERSION="1.21.1" \
    NEOFORGE_VERSION="21.1.233" \
    MEMORY="15360M" \
    ONLINE_MODE="false" \
    DIFFICULTY="normal" \
    MODE="survival" \
    FORCE_GAMEMODE="true" \
    ENABLE_AUTOPAUSE="true" \
    MODRINTH_MODPACK="/modpack.mrpack" \
    MODRINTH_DEFAULT_VERSION_TYPE="release" \
    MODRINTH_LOADER="neoforge" \
    LEVEL="creark" \
    ENTITY_BROADCAST_RANGE_PERCENTAGE="70" \
    SIMULATION_DISTANCE="7" \
    VIEW_DISTANCE="7" \
    ALLOW_FLIGHT="true" \
    OPS="CakeBoy" \
    RCON_CMDS_STARTUP="/gamerule playersSleepingPercentage 0\n/gamerule mobGriefing false" \
    RCON_CMDS_ON_CONNECT="/recipe give @p *"
