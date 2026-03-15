.PHONY: up down logs init-data

# Initialize required data files/directories before starting containers.
# Docker bind-mounts a non-existent path as a directory; this prevents that.
init-data:
	mkdir -p data/logs/bot data/logs/api data/recsys
	@if [ ! -f data/admins.json ]; then \
		echo '[]' > data/admins.json; \
		echo "Created data/admins.json"; \
	fi

up: init-data
	docker-compose up --detach --remove-orphans

down:
	docker-compose down

logs:
	docker-compose logs -f bot
