# Frontend Dockerfile for DocuChat
# Uses Node.js 20 Alpine with Iranian npm mirror for compliance

FROM node:20-alpine

# Set Iranian npm mirror for compliance
# Use first priority mirror: https://package-mirror.liara.ir/repository/npm/
RUN npm config set registry https://package-mirror.liara.ir/repository/npm/ && \
    npm config set strict-ssl false

# Set working directory
WORKDIR /app

# Copy package files from src/frontend
COPY src/frontend/package*.json ./

# Install dependencies with increased timeout and Iranian mirror
RUN npm config set fetch-retry-mintimeout 20000 && \
    npm config set fetch-retry-maxtimeout 120000 && \
    npm install --verbose

# Copy source code
COPY src/frontend/ .

# Expose Vite dev server port
EXPOSE 5173

# Health check for development server
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
  CMD wget --no-verbose --tries=1 --spider http://localhost:5173 || exit 1

# Default command: start Vite dev server with hot reload
CMD ["npm", "run", "dev", "--", "--host"]
