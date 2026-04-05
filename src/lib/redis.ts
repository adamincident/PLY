import Redis from 'ioredis';

import { env } from '../config/env.js';
import { logger } from './logger.js';

export const redis = new Redis(env.REDIS_URL, {
  lazyConnect: true,
  maxRetriesPerRequest: null
});

redis.on('error', (error) => {
  logger.error({ error }, 'Redis client error');
});

export async function connectRedis(): Promise<void> {
  if (redis.status === 'ready' || redis.status === 'connecting') {
    return;
  }

  await redis.connect();
  logger.info('Redis connected');
}

export async function closeRedis(): Promise<void> {
  if (redis.status === 'end') {
    return;
  }

  await redis.quit();
  logger.info('Redis disconnected');
}
