# Frontend Dockerfile for DocuChat
# Uses Node.js 20 Alpine with Iranian npm mirror for compliance

FROM node:20-alpine

# Build arguments for npm mirrors (overridable via --build-arg)
ARG NPM_CONFIG_REGISTRY=https://mirror2.chabokan.net/npm
ARG NPM_CONFIG_STRICT_SSL=false

# Set working directory
WORKDIR /app

# Copy package files from src/frontend
COPY src/frontend/package*.json ./

# Remove lockfile to avoid registry conflicts, set reliable mirror and install
RUN npm config set registry ${NPM_CONFIG_REGISTRY} && \
    npm config set strict-ssl ${NPM_CONFIG_STRICT_SSL} && \
    rm -f package-lock.json && \
    npm install --no-audit --no-fund


# Copy source code
COPY src/frontend/ .

# Expose Vite dev server port
EXPOSE 5173

# Health check for development server
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
  CMD wget --no-verbose --tries=1 --spider http://localhost:5173 || exit 1

# Default command: start Vite dev server with hot reload
CMD ["npm", "run", "dev", "--", "--host"]
