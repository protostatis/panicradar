FROM node:20-alpine

WORKDIR /app

# Copy server package files and install
COPY server/package*.json ./server/
WORKDIR /app/server
RUN npm ci

# Copy shared game domain modules (engine + wagering, tests excluded)
WORKDIR /app
COPY src/engine/GameEngine.js ./src/engine/GameEngine.js
COPY src/game/wagering.js ./src/game/wagering.js

# Copy server source
COPY server/*.js ./server/

WORKDIR /app/server

HEALTHCHECK --interval=15s --timeout=5s --start-period=5s --retries=3 \
  CMD node -e "const http=require('http');http.get('http://localhost:8080/health',r=>{process.exit(r.statusCode===200?0:1)})"

EXPOSE 8080

USER node

CMD ["node", "index.js"]
