FROM node:24-slim
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --omit=dev
COPY server.js database.sql ./
COPY scripts ./scripts
COPY public ./public
ENV NODE_ENV=production PORT=8011
EXPOSE 8011
HEALTHCHECK --interval=30s --timeout=10s --start-period=25s --retries=3 \
  CMD node -e "fetch('http://127.0.0.1:8011/api/health').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"
CMD ["sh", "-c", "node scripts/setup.js && node server.js"]
