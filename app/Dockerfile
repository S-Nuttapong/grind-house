FROM node:24-slim AS build
WORKDIR /app

# The /api rewrite in next.config.ts is resolved at build time.
ARG JOBHUNT_API_URL=http://api:8765
ENV JOBHUNT_API_URL=$JOBHUNT_API_URL NEXT_TELEMETRY_DISABLED=1

COPY package.json package-lock.json next.config.ts tsconfig.json ./
RUN npm ci
COPY src src
RUN npm run build

FROM node:24-slim
WORKDIR /app
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 HOSTNAME=0.0.0.0 PORT=3000

COPY --from=build /app/.next/standalone ./
COPY --from=build /app/.next/static ./.next/static

USER node
EXPOSE 3000
CMD ["node", "server.js"]
