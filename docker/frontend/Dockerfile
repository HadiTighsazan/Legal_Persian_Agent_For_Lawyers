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
# Stage 2: Build — Compile frontend assets for production
# ============================================================
FROM dev AS builder

RUN npm run build

# ============================================================
# Stage 3: Production — Serve with Nginx
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
