# ایمیج پایه از رجیستری آروان‌کلاد
FROM docker.arvancloud.ir/library/node:20-alpine

WORKDIR /app
COPY src/frontend/package*.json ./

# تنظیم میرور ایرانی npm (طبق جدول میرورهای داخلی)
RUN npm config set registry https://package-mirror.liara.ir/repository/npm

# نصب وابستگی‌ها بدون نیاز به پروکسی یا کش‌های پیچیده
RUN rm -f package-lock.json && \
    npm install --no-audit --no-fund --legacy-peer-deps

COPY src/frontend/ .
EXPOSE 5173

HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
  CMD wget --no-verbose --tries=1 --spider http://localhost:5173 || exit 1

CMD ["npm", "run", "dev", "--", "--host"]