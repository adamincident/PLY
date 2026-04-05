import { env } from '../../config/env.js';
import { logger } from '../../lib/logger.js';

export type PolymarketConfig = {
  dataApiUrl: string;
  gammaApiUrl: string;
  wsUrl?: string;
};

export function getPolymarketConfig(): PolymarketConfig {
  return {
    dataApiUrl: env.POLYMARKET_DATA_API_URL,
    gammaApiUrl: env.POLYMARKET_GAMMA_API_URL,
    wsUrl: env.POLYMARKET_WS_URL
  };
}

export function logPolymarketIntegrationTodo(): void {
  logger.warn(
    'TODO: implement official Polymarket WebSocket + polling fallback ingestion in Phase 2'
  );
}
