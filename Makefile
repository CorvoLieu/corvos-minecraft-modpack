DEFAULT_GOAL := dev
.PHONY: dev dev-watch log stop build-client build-server build-mods-zip build-all build-image prod-up prod-log prod-stop install-hooks push pull

# Loads PACK_NAME (and anything else) from .env if present, so `make` targets
# stay in sync with the same single value the Python scripts read via
# python-dotenv. See .env.example.
-include .env
PACK_NAME ?= minecraft-modded
export PACK_NAME

# Symlinks .githooks/pre-commit into .git/hooks/ so it actually runs.
# A prerequisite of every target below, so it self-installs (silently, once)
# the first time anyone runs any `make` command after cloning -- no separate
# setup step to remember. See README's "Pre-commit sync check" section.
install-hooks:
	@hooks_dir=$$(git rev-parse --git-path hooks 2>/dev/null) || exit 0; \
	target="$$(git rev-parse --show-toplevel)/.githooks/pre-commit"; \
	link="$$hooks_dir/pre-commit"; \
	if [ "$$(readlink "$$link" 2>/dev/null)" != "$$target" ]; then \
		mkdir -p "$$hooks_dir"; \
		ln -sf "$$target" "$$link"; \
		echo "Git pre-commit hook installed: $$link -> .githooks/pre-commit"; \
	fi

clean:
	@echo "Cleaning up build artifacts..."
	@rm -f exports/*.mrpack
	@rm -f exports/mods.zip
	@rm -f exports/modpack.mrpack
	@rm -rf .mypy_cache
	@rm -rf .pytest_cache
	@rm -rf __pycache__
	@echo "Done."

clean-dev:
	@echo "Cleaning up dev artifacts..."
	@rm -f exports/mod.mrpack
	@echo "Done cleaning."

push:
	@echo "Pushing local SKLauncher instance state into the repo..."
	@uv run python3 push_instance.py
	@echo "Done."

pull:
	@echo "Pulling repo state into the local SKLauncher instance..."
	@uv run python3 pull_instance.py
	@echo "Done."

# Dev (default): local bind-mounted mod.mrpack (server build, staged from
# exports/server.mrpack), see docker-compose.dev.yml.
dev: install-hooks clean-dev build-server
	@echo "Starting the application (dev)..."
	@cp exports/server.mrpack exports/mod.mrpack
	@docker compose -f docker-compose.dev.yml up -d

dev-watch: install-hooks clean-dev build-server
	@echo "Starting the application (dev)..."
	@cp exports/server.mrpack exports/mod.mrpack
	@docker compose -f docker-compose.dev.yml up -d
	@echo "Tailing the application logs..."
	@docker logs -f minecraft-server-s3

log: install-hooks
	@echo "Tailing the application logs..."
	@docker compose -f docker-compose.dev.yml logs -f

stop: install-hooks
	@echo "Stopping the application..."
	@docker compose -f docker-compose.dev.yml down -v

build-client: install-hooks
	@echo "Building client .mrpack..."
	@uv run python3 build_mrpack.py

build-server: install-hooks
	@echo "Building server .mrpack..."
	@uv run python3 build_mrpack.py --pack-name "$$(printf '%s' "$(PACK_NAME)" | awk '{print toupper(substr($$0,1,1)) substr($$0,2)}')-Server" --output-name server --exclude-file server-excludes.txt

build-mods-zip: install-hooks
	@echo "Building mods-only zip..."
	@uv run python3 build_mrpack.py --mods-zip-only

build-all: build-client build-server build-mods-zip

# Prod (local testing only, see docker-compose.prod.yml). Builds the client
# mrpack (exports/client.mrpack, which the Dockerfile COPYs directly) and
# builds the image locally -- doesn't push anywhere.
build-image: build-client
	@echo "Building local image..."
	@docker build --build-arg PACK_NAME=$(PACK_NAME) -t $(PACK_NAME)-modpack:local .

stg-up: install-hooks
	@echo "Starting the application (staging compose, local test)..."
	@docker compose -f docker-compose.stg.yml up -d

stg-log: install-hooks
	@echo "Tailing the application logs (staging)..."
	@docker compose -f docker-compose.stg.yml logs -f

stg-stop: install-hooks
	@echo "Stopping the application (staging)..."
	@docker compose -f docker-compose.stg.yml down -v

prod-up: install-hooks
	@echo "Starting the application (prod compose, local test)..."
	@docker compose -f docker-compose.prod.yml up -d

prod-log: install-hooks
	@echo "Tailing the application logs (prod)..."
	@docker compose -f docker-compose.prod.yml logs -f

prod-stop: install-hooks
	@echo "Stopping the application (prod)..."
	@docker compose -f docker-compose.prod.yml down