# Nginx Reverse Proxy
FROM nginx:alpine

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

# Health check using built-in wget instead of curl
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
  CMD wget -q --spider http://localhost/health/ || exit 1

# Start nginx
CMD ["nginx", "-g", "daemon off;"]
