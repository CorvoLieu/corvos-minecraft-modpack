DEFAULT_GOAL := run
.PHONY: run run-watch log stop build-client build-server build-mods-zip build-all

run:
	@echo "Starting the application..."
	@docker compose up -d

run-watch:
	@echo "Starting the application..."
	@docker compose up -d
	@echo "Tailing the application logs..."
	@docker logs -f minecraft-server-s3

log:
	@echo "Tailing the application logs..."
	@docker compose logs -f

stop:
	@echo "Stopping the application..."
	@docker compose down -v

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