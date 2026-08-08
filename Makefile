DEFAULT_GOAL := run
.PHONY: run run-watch log stop build-client build-server build-mods-zip build-all build-image prod-up prod-log prod-stop

# Dev (default): local bind-mounted modpack.mrpack, see docker-compose.dev.yml.
run:
	@echo "Starting the application (dev)..."
	@docker compose -f docker-compose.dev.yml up -d

run-watch:
	@echo "Starting the application (dev)..."
	@docker compose -f docker-compose.dev.yml up -d
	@echo "Tailing the application logs..."
	@docker logs -f minecraft-server-s3

log:
	@echo "Tailing the application logs..."
	@docker compose -f docker-compose.dev.yml logs -f

stop:
	@echo "Stopping the application..."
	@docker compose -f docker-compose.dev.yml down -v

build-client:
	@echo "Building client .mrpack..."
	@uv run python3 export_mrpack.py

build-server:
	@echo "Building server .mrpack..."
	@uv run python3 export_mrpack_server.py

build-mods-zip:
	@echo "Building mods-only zip..."
	@uv run python3 export_mods.py

build-all: build-client build-server build-mods-zip

# Prod (local testing only, see docker-compose.prod.yml). Builds the client
# mrpack, stages it as exports/modpack.mrpack for the Dockerfile, and builds
# the image locally -- doesn't push anywhere.
build-image: build-client
	@echo "Staging modpack for image build..."
	@cp $$(ls -t exports/Creark-*.mrpack | grep -v -- '-Server-' | head -1) exports/modpack.mrpack
	@echo "Building local image..."
	@docker build -t creark-modpack:local .

prod-up:
	@echo "Starting the application (prod compose, local test)..."
	@docker compose -f docker-compose.prod.yml up -d

prod-log:
	@echo "Tailing the application logs (prod)..."
	@docker compose -f docker-compose.prod.yml logs -f

prod-stop:
	@echo "Stopping the application (prod)..."
	@docker compose -f docker-compose.prod.yml down