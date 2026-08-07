DEFAULT_GOAL := run
.PHONY: run stop log

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