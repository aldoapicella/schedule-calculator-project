# Schedule Calculator Project

This repository implements a three-stage UTP schedule pipeline:

1. `scrape_utp.py` scrapes subject groups from the UTP portal into JSON.
2. `data_extractor/inserter.py` validates that JSON and imports it into Postgres.
3. `data_extractor/calculator.py` queries Postgres and computes the best schedule.

The shared logic lives in `schedule_calculator/`:

- `domain/`: dataclasses and pure scheduling/import rules
- `application/`: use-case orchestration for scraping, importing, and scheduling
- `infrastructure/`: portal, Postgres, config, and logging adapters

## Setup

Python dependencies are not pinned in this repo yet, but the runtime expects:

- `requests`
- `beautifulsoup4`
- `psycopg2`

The database stack is provided by Docker Compose:

```bash
docker compose up -d
```

For environment variables, choose one of the examples:

```bash
cp .env.example.host .env
```

or

```bash
cp .env.example.docker .env
```

Host mode is for running the Python scripts directly on your machine. Docker mode is for running them inside a container network where Postgres resolves as `postgres`.

## Commands

Scrape subjects into a JSON artifact:

```bash
python scrape_utp.py --subject-ids 0698,0709
```

Import a scraped payload into Postgres:

```bash
python data_extractor/inserter.py --input artifacts/scraped_groups.json
```

Calculate the best schedule:

```bash
python data_extractor/calculator.py \
  --subjects 0698,0709,0760 \
  --required-subjects 0760 \
  --available-start 17:00 \
  --available-end 23:00 \
  --province PANAMÁ
```

All entrypoints support:

- `--env-file <path>` to override the default `.env`
- `--log-file <path>` to write logs to a file explicitly
- `--verbose` to enable debug logging

By default, generated scraper output goes to `artifacts/scraped_groups.json`. No log file is created unless `--log-file` is passed.

## Configuration

Database configuration precedence:

1. explicit `--env-file`
2. local `.env` if present
3. process environment

If `POSTGRES_URI` is set, it overrides the component-based config. Otherwise the DSN is built from:

- `POSTGRES_USER`
- `POSTGRES_PASSWORD`
- `POSTGRES_DB`
- `POSTGRES_HOST`
- `POSTGRES_PORT`

Portal credentials come from:

- `UTP_USERNAME`
- `UTP_PASSWORD`
- `UTP_PROFILE_LABEL` (optional, defaults to `Estudiantes`)
- `UTP_BASE_URL` (optional, defaults to `https://matricula.utp.ac.pa/`)

## Quality

Run the unit suite with:

```bash
python3 -m unittest discover -s tests -v
```

The tests cover domain rules, config handling, CLI contracts, scheduler behavior, importer validation, and portal parsing/failure handling.

## Operations

See [`docs/runbook.md`](docs/runbook.md) for the production-oriented runbook.
