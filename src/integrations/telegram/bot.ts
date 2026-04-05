import { env } from '../../config/env.js';
import { logger } from '../../lib/logger.js';

export function telegramIsConfigured(): boolean {
  return Boolean(env.TELEGRAM_BOT_TOKEN && env.TELEGRAM_CHAT_ID);
}

export function logTelegramIntegrationTodo(): void {
  logger.warn('TODO: implement Telegram command + alerts integration in Phase 6');
}
