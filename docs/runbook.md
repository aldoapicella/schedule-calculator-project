# Runbook

## Runtime Modes

### Host mode

Use `.env.example.host` when you run the Python scripts on your machine and Postgres is exposed on `localhost:5432`.

Typical flow:

```bash
cp .env.example.host .env
docker compose up -d
python scrape_utp.py --subject-ids 0698,0709 --group-concurrency 6
python data_extractor/inserter.py --input artifacts/scraped_groups.json
python data_extractor/calculator.py --subjects 0698,0709 --available-start 17:00 --available-end 23:00 --province PANAMÁ
```

### Docker-network mode

Use `.env.example.docker` when the application code runs inside a container network and Postgres resolves as `postgres`.

Typical DB settings:

- `POSTGRES_HOST=postgres`
- `POSTGRES_PORT=5432`

## Artifacts

Generated runtime output should live under `artifacts/`.

Expected artifacts:

- `artifacts/scraped_groups.json`
- optional custom log files when `--log-file` is passed

Tracked scratch files such as `data_extractor/data.json` and `data_extractor/schedule.log` are intentionally removed from the repo.

## CLI Behavior

Exit codes:

- `0`: success
- `1`: runtime or data failure
- `2`: configuration or usage failure

Logging:

- default: concise INFO/WARN logging to stderr
- `--verbose`: enables DEBUG logging
- `--log-file`: writes logs to an explicit file path
- scraper `--group-concurrency`: fetches group detail pages in parallel per subject, default `6`

## Failure Modes

### `Configuration error`

Common causes:

- missing `UTP_USERNAME` or `UTP_PASSWORD`
- missing Postgres settings
- `--env-file` points to a file that does not exist

Action:

- verify `.env`, `.env.example.host`, or `.env.example.docker`
- verify whether you are running in host mode or Docker-network mode

### `Scraping failed`

Common causes:

- portal login page changed
- expected portal forms or links are missing
- repeated HTTP failures
- wrong `UTP_PROFILE_LABEL`

Action:

- retry with `--verbose`
- confirm credentials manually in the portal
- inspect whether the portal HTML has changed

### `Import failed`

Common causes:

- missing or malformed JSON input
- invalid province values
- scraped sessions that do not map back to a subject code
- Postgres connectivity or write failures

Action:

- validate the JSON file exists and contains an array
- re-run scraper and inspect the output
- verify Postgres connectivity and schema state

### `Scheduling failed`

Common causes:

- missing DB config
- Postgres read failures
- malformed time inputs

Action:

- confirm CLI arguments
- confirm the database is populated
- use `--verbose` to inspect rejection reasons

## Operational Notes

- The scheduler preserves the current business rules: out-of-province groups are allowed only when fully virtual, lab groups require theory, and the best solution still requires at least two enrollments.
- The scheduler now optimizes search order internally by exploring subjects with fewer candidate enrollments first, but the final output preserves the original user subject order.
- The portal adapter retries transient request failures with small backoff before surfacing a request error.
- The scraper keeps subjects sequential for portal stability, but group detail pages within each subject are fetched with bounded parallelism to reduce live scrape time without changing output order.
