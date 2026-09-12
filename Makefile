.PHONY: up down migrate downgrade seed ingest relay smoke integration-smoke external-dod soak audit test lint typecheck

up:
	docker compose -f deploy/docker-compose.yml up -d

down:
	docker compose -f deploy/docker-compose.yml down

migrate:
	python -m alembic -c alembic.ini upgrade head

downgrade:
	python -m alembic -c alembic.ini downgrade base

seed:
	python -m core_data.cli source import deploy/seed.opml

ingest:
	python -m core_data.cli ingest run --all

relay:
	python -m core_data.scripts.relay --once

smoke:
	python -m core_data.scripts.smoke

integration-smoke:
	python -m core_data.scripts.integration_smoke --require-external

external-dod:
	python -m core_data.scripts.external_dod --soak-hours 24 --interval-sec 300

soak:
	python -m core_data.scripts.soak --hours 24 --interval-sec 300 --seed-fixture

audit:
	python -m core_data.scripts.audit_dod

test:
	python -m pytest -q tests --cov=core_data --cov-config=.coveragerc --cov-report=term-missing --cov-fail-under=80

lint:
	python -m ruff check .

typecheck:
	python -m mypy --config-file pyproject.toml src
