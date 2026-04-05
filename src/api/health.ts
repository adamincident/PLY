import { FastifyInstance } from 'fastify';

import { prisma } from '../db/prisma.js';
import { redis } from '../lib/redis.js';

export async function registerHealthRoutes(app: FastifyInstance): Promise<void> {
  app.get('/health', async () => {
    const [dbStatus, redisStatus] = await Promise.all([
      prisma
        .$queryRaw`SELECT 1`
        .then(() => 'ok')
        .catch(() => 'error'),
      redis.ping().then(() => 'ok').catch(() => 'error')
    ]);

    const status = dbStatus === 'ok' && redisStatus === 'ok' ? 'ok' : 'degraded';

    return {
      status,
      services: {
        postgres: dbStatus,
        redis: redisStatus
      },
      timestamp: new Date().toISOString()
    };
  });
}
