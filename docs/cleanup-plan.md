# Cleanup Plan and Repository Analysis

## Legacy repository findings

The original repository contained a single Python worker and minimal process metadata:

- `copybot.py`: monolithic script mixing discovery, risk, trading simulation, persistence, and Telegram side effects in one file.
- `requirements.txt`: only `requests`; no reproducible lockfile or modular dependencies.
- `Procfile`: legacy process launcher for the Python worker.

## Why these files are obsolete for the rebuild

- The target stack is TypeScript/Node.js with Fastify, Redis, PostgreSQL, Prisma, BullMQ, and Docker.
- The legacy Python script is tightly coupled and not aligned with required modular architecture.
- Legacy process and dependency files do not apply to the new runtime.

## Safe cleanup strategy

1. Remove Python-specific runtime files (`copybot.py`, `requirements.txt`, `Procfile`).
2. Preserve reusable conceptual behavior only as domain requirements (risk checks, paper mode) in documentation and schema design.
3. Introduce a clean modular structure under `/src` with phase boundaries.
4. Add environment validation, service connections, and health checks before business logic.

## Phase implementation order

- **Phase 1**: foundation only (server, config, Redis, PostgreSQL + Prisma, logging, Docker).
- **Phase 2+**: incremental domain implementation with TODO markers where API certainty is required.
