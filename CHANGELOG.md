# Changelog

All notable changes to this project are recorded here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses [Semantic Versioning](https://semver.org/).

## [0.1.0] - 2026-10-27

### Added

- PostgreSQL 18 in `docker-compose.yml`, run under an init process with a health check over TCP, lock waits logged and checkpoints spaced out.
- SQL: an idempotent schema and a seed that leaves a populated table alone, the lesson's inspection queries, six idempotent migrations (transactional where PostgreSQL allows it, with a short `lock_timeout`) each with a down script, the three naive statements, the correlated month for the plan flip, and plans before and after as `.sql` plus captured `.txt`.
- A layered Python package (`domain`, `application`, `infrastructure`, `interfaces`) with the dependency rule enforced by import-linter: percentiles, windows and the p99 bar as pure domain code, each experiment a use case over ports, adapters for PostgreSQL and the threaded load, a replay command (`make run`, `make measure`), a load command and a health command.
- The load script reports p99 per second counting operations still waiting, so a stall shows even when nothing completes; results say how busy the machine was.
- Unit, integration and end-to-end tests with coverage (domain and application at 100%); ruff, mypy `strict`, import-linter and `pip-audit` in CI; hashed lock files.
