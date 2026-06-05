# Proxy Build Fix Plan

## Problem
`host.docker.internal` resolves **only at runtime** (when the container is running), **not at build time** (when `docker build` executes). During `docker-compose build`, the `apt-get update` command tries to use `http://host.docker.internal:10808` as proxy, but `host.docker.internal` cannot be resolved, causing all Debian package downloads to fail.

## Solution
Use Docker **Build Arguments** (`ARG`) to pass the host machine's IP address into the Dockerfile at build time.

## Changes Required

### 1. [`docker/backend/Dockerfile`](docker/backend/Dockerfile)

Add `ARG HOST_IP` at two levels:
- **Top-level** (before `FROM`): default value `host.docker.internal` — this is the fallback for runtime
- **After `FROM`** (with `ARG HOST_IP` again): to make it available in the build stage

Use `${HOST_IP}` in the `ENV HTTP_PROXY` lines instead of hardcoded `host.docker.internal`.

```dockerfile
ARG HOST_IP=host.docker.internal

FROM python:3.11-slim-bookworm

ARG HOST_IP

ENV HTTP_PROXY=http://${HOST_IP}:10808
ENV HTTPS_PROXY=http://${HOST_IP}:10808
ENV http_proxy=http://${HOST_IP}:10808
ENV https_proxy=http://${HOST_IP}:10808
```

### 2. [`docker-compose.yml`](docker-compose.yml)

Add `build.args` to the `backend` service definition to pass the host IP:

```yaml
backend:
  build:
    context: .
    dockerfile: ./docker/backend/Dockerfile
    args:
      HOST_IP: 192.168.1.112
```

Also add `build.args` to `test` service similarly (optional, since test uses `--profile test`).

### 3. Build Command

```bash
docker-compose build --no-cache backend
```

Or if you want to pass the IP dynamically without hardcoding in docker-compose.yml:

```bash
docker-compose build --no-cache --build-arg HOST_IP=192.168.1.112 backend
```

## Why This Works
- At **build time**: `HOST_IP=192.168.1.112` → proxy URL becomes `http://192.168.1.112:10808` → V2Ray on your laptop accepts the connection
- At **runtime**: `HOST_IP` defaults to `host.docker.internal` (because `extra_hosts` in docker-compose.yml maps it via `host-gateway`) → proxy URL becomes `http://host.docker.internal:10808` → works via Docker's internal DNS

## Note on `docker-compose.yml` Runtime Proxy
The runtime proxy env vars in `docker-compose.yml` (under `environment:`) already use `host.docker.internal` which works at runtime because of the `extra_hosts` directive. No changes needed there.
