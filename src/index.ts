import { closeDatabase, connectDatabase } from './db/prisma.js';
import { logger } from './lib/logger.js';
import { closeRedis, connectRedis } from './lib/redis.js';
import { startServer } from './server.js';

async function bootstrap() {
  await connectDatabase();
  await connectRedis();
  const app = await startServer();

  const shutdown = async (signal: NodeJS.Signals) => {
    logger.info({ signal }, 'Shutting down');

    await app.close();
    await Promise.all([closeRedis(), closeDatabase()]);

    process.exit(0);
  };

  process.on('SIGINT', shutdown);
  process.on('SIGTERM', shutdown);
}

bootstrap().catch((error) => {
  logger.fatal({ error }, 'Bootstrap failed');
  process.exit(1);
});
