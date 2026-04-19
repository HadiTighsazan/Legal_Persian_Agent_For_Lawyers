# Scripts Directory

This directory contains utility scripts for testing, verification, and development tasks.

## Current Scripts

### 1. `verify_mt09.py`
**Purpose**: Verifies that MT-09 (Initialize Django Project Structure) is properly implemented.

**Usage**:
```bash
python scripts/verify_mt09.py
```

**What it checks**:
- All required Django files and directories exist
- Settings are properly configured (core app, custom user model, Celery, logging)
- Health endpoints are configured in URLs
- Docker configuration includes health checks
- Environment variables are set up

### 2. `test_mt09_final.py`
**Purpose**: Comprehensive end-to-end test for MT-09 after debugging.

**Usage**:
```bash
python scripts/test_mt09_final.py
```

**What it tests**:
- All Docker containers are running and healthy
- Health endpoints return 200 OK with proper JSON
- Admin, Swagger, and ReDoc endpoints work
- API endpoints return appropriate status codes (404 for not implemented endpoints)
- Frontend dev server is accessible

## Script Categories

### Verification Scripts
These scripts check that the project structure and configuration are correct. They're useful for:
- Validating new installations
- Checking CI/CD pipeline requirements
- Verifying deployment readiness

### Test Scripts
These scripts perform actual HTTP requests and service checks. They're useful for:
- End-to-end testing
- Debugging service integration
- Health monitoring

## Adding New Scripts

When adding new scripts:
1. Use descriptive names (e.g., `verify_mt10.py`, `test_frontend_integration.py`)
2. Include a docstring explaining the script's purpose
3. Add an entry to this README
4. Follow Python best practices (type hints, error handling, etc.)

## Running Scripts

All scripts should be run from the project root directory:
```bash
cd /path/to/rag-project
python scripts/script_name.py
```

## Dependencies

Scripts may require:
- Python 3.11+
- `curl` command-line tool (for HTTP tests)
- Docker and docker-compose (for container tests)
- Project dependencies (Django, etc.)

## Notes

- These scripts are for development and verification purposes only
- They're not part of the production application
- Some scripts may make HTTP requests to local services
- Always check script requirements before running