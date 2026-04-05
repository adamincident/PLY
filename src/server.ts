import helmet from '@fastify/helmet';
import Fastify from 'fastify';

import { registerHealthRoutes } from './api/health.js';
import { env } from './config/env.js';
import { logger } from './lib/logger.js';

export function buildServer() {
  const app = Fastify({
    logger,
    trustProxy: true
  });

  app.register(helmet);
  app.register(registerHealthRoutes);

  app.get('/', async () => ({
    service: 'ply',
    phase: 'foundation',
    message: 'Polymarket bot foundation is running'
  }));

  return app;
}

export async function startServer() {
  const app = buildServer();

  await app.listen({
    host: env.HOST,
    port: env.PORT
  });

  logger.info({ host: env.HOST, port: env.PORT }, 'Fastify server started');
  return app;
}
