# WIP Context — Remove Iranian Mirrors from Docker Build

## What Was Just Completed

Removed all Iranian mirror configurations from Docker build files to use original/main repositories directly.

### Changes Made

1. **`docker/backend/Dockerfile`** — Removed Liara PyPI mirror:
   - Removed `--extra-index-url https://package-mirror.liara.ir/repository/pypi`
   - Removed `--trusted-host package-mirror.liara.ir`
   - Updated comment from "Install Python dependencies via Liara internal mirror" to "Install Python dependencies from official PyPI index"
   - Removed the "Uses Liara internal PyPI mirror" header comment

2. **`docker/frontend/Dockerfile`** — Removed ArvanCloud registry and proxy:
   - Changed base image from `docker.arvancloud.ir/library/node:20-alpine` to official `node:20-alpine` in both `dev` and `deps` stages
   - Removed all HTTP_PROXY/HTTPS_PROXY environment variables (lines setting proxy to `host.docker.internal:10808`)

3. **`docker/nginx/Dockerfile`** — No changes needed (already uses official `nginx:alpine`)

## Current State
- All Dockerfiles now pull base images and packages directly from official/main sources (Docker Hub, npmjs.org, PyPI)
- No dependency on Iranian cloud providers (Liara, ArvanCloud) or local proxies

## Next Steps
1. Run `docker-compose build` to verify the build succeeds with original mirrors
2. If behind a corporate VPN/firewall, ensure Docker has direct internet access

## Reference Doc Changes
- No database schema or API changes
