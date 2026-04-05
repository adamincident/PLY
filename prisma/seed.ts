import { BotMode, PrismaClient } from '@prisma/client';

const prisma = new PrismaClient();

async function main() {
  await prisma.portfolio.upsert({
    where: { id: 'seed-paper-portfolio' },
    update: {},
    create: {
      id: 'seed-paper-portfolio',
      mode: BotMode.PAPER,
      cash: '10000',
      equity: '10000',
      dailyPnl: '0',
      totalPnl: '0',
      maxDailyLoss: '500',
      maxPositionSize: '500'
    }
  });

  await prisma.wallet.upsert({
    where: { address: '0x0000000000000000000000000000000000000000' },
    update: {},
    create: {
      address: '0x0000000000000000000000000000000000000000',
      label: 'example-wallet',
      score: 0.5,
      consistency: 0.5,
      tradeCount: 0,
      recencyScore: 0,
      drawdownProxy: 0,
      diversification: 0
    }
  });
}

main()
  .then(async () => {
    await prisma.$disconnect();
  })
  .catch(async (error) => {
    console.error(error);
    await prisma.$disconnect();
    process.exit(1);
  });
