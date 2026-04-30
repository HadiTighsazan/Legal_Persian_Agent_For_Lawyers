# Fix PostgreSQL Container Healthcheck Issue

## Root Cause Analysis

Based on the PostgreSQL container logs, there are **two distinct problems**:

### Problem 1: `init.sql` Syntax Error (Historical)
```
ERROR: syntax error at or near "CREATE" at character 26
STATEMENT: ALTER DATABASE template1 CREATE EXTENSION IF NOT EXISTS vector;
```
The command `ALTER DATABASE template1 CREATE EXTENSION ...` is invalid PostgreSQL syntax. The correct approach is:
```sql
ALTER DATABASE template1 SET search_path TO public;
CREATE EXTENSION IF NOT EXISTS vector;
```
However, since the database directory already exists ("Skipping initialization"), this error only occurred on the **first** container startup and is not the current issue.

### Problem 2: Healthcheck Connecting to Wrong Database (Active Issue)
```
FATAL: database "docuchat_user" does not exist
```
The healthcheck command in `docker-compose.yml` line 40:
```yaml
test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER:-docuchat_user}"]
```
`pg_isready -U docuchat_user` tries to connect to a database named **`docuchat_user`** (same as the user), but the actual database is **`docuchat_db`** (defined by `POSTGRES_DB`). The `-d` flag is missing to specify the target database.

### Problem 3: pgvector Extension Not Installed
Because `init.sql` failed on first run, the `vector` extension was never installed on the `docuchat_db` database. This will break vector search functionality.

---

## Fix Steps

### Step 1: Fix `docker-compose.yml` — Healthcheck

**File:** [`docker-compose.yml`](docker-compose.yml:40)

**Change:**
```yaml
# BEFORE:
test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER:-docuchat_user}"]

# AFTER:
test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER:-docuchat_user} -d ${POSTGRES_DB:-docuchat_db}"]
```

### Step 2: Create/Replace `docker/postgres/init.sql`

**File:** [`docker/postgres/init.sql`](docker/postgres/init.sql)

Create this file with correct syntax:
```sql
-- Enable pgvector extension on the application database
CREATE EXTENSION IF NOT EXISTS vector;

-- Also enable on template1 so future databases get it automatically
ALTER DATABASE template1 SET search_path TO public;
```

### Step 3: Recreate PostgreSQL Container

Run these commands in order:
```bash
# Stop all containers and remove the PostgreSQL volume (WARNING: deletes all data)
cd /c/Users/hadit/Desktop/rag-project
docker-compose down -v

# Restart everything
docker-compose up -d

# Verify health status
docker-compose ps
```

### Step 4: Verify

Check that:
1. `docker-compose ps` shows `docuchat_postgres` as `healthy`
2. `docker-compose logs postgres` shows no FATAL errors
3. The vector extension is installed: `docker-compose exec postgres psql -U docuchat_user -d docuchat_db -c "SELECT * FROM pg_extension WHERE extname='vector';"`

---

## Important Notes

- `docker-compose down -v` **deletes all PostgreSQL data** (documents, users, etc.). If you need to preserve data, we can try an alternative approach:
  - Connect to the running container and manually create the database: `docker-compose exec postgres createdb -U docuchat_user docuchat_db`
  - Then install the extension: `docker-compose exec postgres psql -U docuchat_user -d docuchat_db -c "CREATE EXTENSION IF NOT EXISTS vector;"`
- The `-v` flag is the cleanest solution and recommended if this is a development environment.
