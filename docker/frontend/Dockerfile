# ============================================================
# Stage 1: Build — Compile frontend assets
# ============================================================
FROM docker.arvancloud.ir/library/node:20-alpine AS builder

WORKDIR /app
COPY src/frontend/package*.json ./

# Configure Iranian npm mirror
RUN npm config set registry https://package-mirror.liara.ir/repository/npm

# Install all dependencies (including devDependencies needed for build)
RUN rm -f package-lock.json && \
    npm install --no-audit --no-fund --legacy-peer-deps

COPY src/frontend/ .
RUN npm run build

# ============================================================
# Stage 2: Production — Serve with Nginx
# ============================================================
FROM nginx:alpine

RUN rm /etc/nginx/conf.d/default.conf
COPY docker/nginx/nginx.conf /etc/nginx/nginx.conf
COPY --from=builder /app/dist /usr/share/nginx/html

RUN mkdir -p /etc/nginx/ssl /static /media

EXPOSE 80 443

HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
  CMD wget -q --spider http://localhost/health/ || exit 1

CMD ["nginx", "-g", "daemon off;"]
