.PHONY: up down logs rabbit test

## Start the full stack (build images, run detached)
up:
	docker-compose up -d --build

## Stop and remove containers + named volumes
down:
	docker-compose down -v

## Stream logs from all services
logs:
	docker-compose logs -f

## Open RabbitMQ management UI in the default browser
rabbit:
	open http://localhost:15672

## Run integration tests
test:
	pytest tests/integration/ -v
