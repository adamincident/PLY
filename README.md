# PLY — Polymarket Bot (Rebuild)

This repository has been rebuilt into a modular TypeScript architecture for a production-grade Polymarket copy-trading system.

## Current status

- ✅ Phase 1 foundation is implemented.
- 🚧 Trading logic intentionally deferred to later phases.

## Stack

- Node.js + TypeScript
- Fastify API server
- Redis (ioredis)
- PostgreSQL + Prisma
- pino logging
- zod configuration validation
- Docker Compose (PostgreSQL + Redis)

## Project structure

```text
/src
  /config
  /lib
  /integrations/polymarket
  /integrations/telegram
  /domain/scoring
  /domain/signals
  /domain/execution
  /domain/risk
  /domain/portfolio
  /jobs
  /api
  /db
  /tests
```

## Local setup

1. Install dependencies:

   ```bash
   npm install
   ```

2. Copy env file:

   ```bash
   cp .env.example .env
   ```

3. Start infrastructure:

   ```bash
   docker compose up -d postgres redis
   ```

4. Generate Prisma client and run migrations:

   ```bash
   npm run prisma:generate
   npm run prisma:migrate -- --name init
   npm run prisma:seed
   ```

5. Start app:

   ```bash
   npm run dev
   ```

## Endpoints

- `GET /` — service metadata
- `GET /health` — Redis + PostgreSQL health probe

## Phase notes

- Phase 2 (data ingestion): TODO with official Polymarket websocket endpoint + fallback polling.
- Phase 6 (Telegram): TODO with official Telegram Bot API integration.

When API details are uncertain, TODO markers are left explicitly to avoid guessing.
