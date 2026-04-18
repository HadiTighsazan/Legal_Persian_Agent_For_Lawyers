# Nginx Reverse Proxy
FROM nginx:alpine

# Configure Iranian Alpine mirrors (for compliance with local network restrictions)
RUN echo "https://mirror1.liara.ir/alpine/v3.23/main" > /etc/apk/repositories && \
    echo "https://mirror1.liara.ir/alpine/v3.23/community" >> /etc/apk/repositories

# Install curl for health checks
RUN apk update && apk add --no-cache curl

# Remove default nginx configuration
RUN rm /etc/nginx/conf.d/default.conf

# Copy custom nginx configuration
COPY nginx.conf /etc/nginx/nginx.conf

# Create SSL directory for future HTTPS support
RUN mkdir -p /etc/nginx/ssl

# Create directories for static and media files
RUN mkdir -p /static /media /usr/share/nginx/html

# Expose ports
EXPOSE 80 443

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
  CMD curl -f http://localhost/health/ || exit 1

# Start nginx
CMD ["nginx", "-g", "daemon off;"]
