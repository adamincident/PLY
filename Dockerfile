FROM node:20-alpine AS base
WORKDIR /app

COPY package*.json ./
RUN npm ci

COPY tsconfig.json eslint.config.js ./
COPY prisma ./prisma
COPY src ./src
RUN npm run build

FROM node:20-alpine AS runtime
WORKDIR /app
ENV NODE_ENV=production

COPY package*.json ./
RUN npm ci --omit=dev
COPY --from=base /app/dist ./dist
COPY prisma ./prisma

CMD ["node", "dist/index.js"]
