import { PrismaClient } from '@prisma/client';

import { logger } from '../lib/logger.js';

export const prisma = new PrismaClient({
  log: ['warn', 'error']
});

export async function connectDatabase(): Promise<void> {
  await prisma.$connect();
  logger.info('PostgreSQL connected through Prisma');
}

export async function closeDatabase(): Promise<void> {
  await prisma.$disconnect();
  logger.info('PostgreSQL disconnected');
}
