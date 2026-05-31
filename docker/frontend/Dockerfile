# ============================================================
# Stage 1: Dev — For development server (npm run dev)
# ============================================================
FROM docker.arvancloud.ir/library/node:20-alpine AS dev

WORKDIR /app
COPY src/frontend/package*.json ./

# Install all dependencies (including devDependencies)
RUN npm install --no-audit --no-fund --legacy-peer-deps

COPY src/frontend/ .

EXPOSE 5173
CMD ["npm", "run", "dev", "--", "--host"]

# ============================================================
# Stage 2: Dependencies — Install production deps only
# ============================================================
FROM docker.arvancloud.ir/library/node:20-alpine AS deps

WORKDIR /app
COPY src/frontend/package*.json ./
RUN npm install --no-audit --no-fund --legacy-peer-deps

# ============================================================
# Stage 3: Build — Compile frontend assets for production
# ============================================================
FROM deps AS builder

COPY src/frontend/ .

# Explicitly set production API URL — overrides any .env file
# This ensures the built JS bundle uses /api (same-origin via nginx proxy)
# instead of http://localhost:8000 (which would cause CORS errors).
ARG VITE_API_URL=/api
ENV VITE_API_URL=/api

RUN npm run build

# ============================================================
# Stage 4: Production — Serve with Nginx
# ============================================================
FROM nginx:alpine AS production

RUN rm /etc/nginx/conf.d/default.conf
COPY docker/nginx/nginx.conf /etc/nginx/nginx.conf
COPY --from=builder /app/dist /usr/share/nginx/html

RUN mkdir -p /etc/nginx/ssl /static /media

EXPOSE 80 443

HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
  CMD wget -q --spider http://localhost/health/ || exit 1

CMD ["nginx", "-g", "daemon off;"]
