# Manual Test Guide: Epic E-05 — Embedding & Vector Storage

## راهنمای تست دستی برای اپیک Embedding & Vector Storage

این راهنما شامل **7 سناریوی تست** است که تمام قابلیت‌های E05 را پوشش می‌دهد:

| # | سناریو | اندپوینت | هدف |
|---|--------|----------|------|
| 1 | تست پایه: آپلود + پردازش + Embedding | `POST /documents/{id}/embed/` | اطمینان از عملکرد کامل زنجیره |
| 2 | تست وضعیت Task | `GET /tasks/{task_id}/` | پیگیری پیشرفت task |
| 3 | تست Batch Embedding | `POST /chunks/batch-embed/` | Embedding دسته‌ای chunkها |
| 4 | تست Re-embed | `POST /chunks/{chunk_id}/re-embed/` | بازتولید embedding یک chunk |
| 5 | تست خطاها (Error Scenarios) | همه اندپوینت‌ها | 404, 403, 401, 400 |
| 6 | تست Re-embed Script | `scripts/reembed_all.py` | بازنشانی همه embeddingها |
| 7 | تست pgvector Index | `python manage.py check` | تأیید وجود ivfflat index |

---

## پیش‌نیازها

1. **داکر در حال اجراست:**
   ```bash
   cd /c/Users/hadit/Desktop/rag-project
   docker-compose ps
   ```
   باید `backend`، `celery_worker`، `postgres`، `redis` رو `Up` ببینی.

2. **فایل `.env`** با `OPENAI_API_KEY` معتبر وجود دارد.

3. **migration‌ها اجرا شده:**
   ```bash
   docker-compose exec backend python manage.py migrate
   ```

4. **یک کاربر ثبت‌نام شده و توکن JWT معتبر دارید.**

---

## مرحله 0: ثبت‌نام و دریافت توکن

```bash
# ثبت‌نام کاربر جدید
curl -X POST http://localhost:8000/auth/register/ \
  -H "Content-Type: application/json" \
  -d '{
    "email": "embed-test@example.com",
    "password": "testpass123",
    "full_name": "Embed Test User"
  }'
```

**خروجی مورد انتظار:** کد `201 Created` با `accessToken` و `refreshToken`.

> اگر از قبل کاربر داری، از لاگین استفاده کن:
> ```bash
> curl -X POST http://localhost:8000/auth/login/ \
>   -H "Content-Type: application/json" \
>   -d '{"email": "embed-test@example.com", "password": "testpass123"}'
> ```

**توکن رو ذخیره کن:**
```bash
TOKEN="<accessToken_اینجا_بذار>"
```

---

## سناریو 1: تست پایه — آپلود + پردازش + Embedding کامل

این سناریو **مهم‌ترین تست** است. کل زنجیره از آپلود فایل تا تولید embedding را بررسی می‌کند.

### گام 1.1: آپلود فایل

```bash
# یک فایل PDF تستی بساز (یا از یک فایل PDF واقعی استفاده کن)
echo "This is a test document for embedding pipeline testing. It contains multiple sentences to ensure chunking works correctly. The quick brown fox jumps over the lazy dog. Machine learning is transforming how we interact with documents." > /tmp/test-embed.pdf

# آپلود فایل
curl -X POST http://localhost:8000/documents/upload/ \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@/tmp/test-embed.pdf"
```

**خروجی مورد انتظار:** کد `201 Created`
```json
{
  "id": "uuid-اینجا",
  "title": "test-embed.pdf",
  "original_filename": "test-embed.pdf",
  "file_size": ...,
  "status": "uploaded",
  ...
}
```

**`DOCUMENT_ID` رو ذخیره کن:**
```bash
DOCUMENT_ID="<uuid_از_خروجی_بالا>"
```

### گام 1.2: شروع پردازش (Extract + Chunk)

```bash
curl -X POST "http://localhost:8000/documents/$DOCUMENT_ID/process/" \
  -H "Authorization: Bearer $TOKEN"
```

**خروجی مورد انتظار:** کد `202 Accepted`
```json
{
  "task_id": "celery-task-id-...",
  "status": "pending",
  "document_id": "<uuid>"
}
```

### گام 1.3: صبر کن تا پردازش کامل بشه (حدود 5-10 ثانیه)

```bash
# بعد از 5 ثانیه وضعیت رو چک کن
sleep 5
curl -X GET "http://localhost:8000/documents/$DOCUMENT_ID/processing-status/" \
  -H "Authorization: Bearer $TOKEN"
```

**خروجی مورد انتظار:** کد `200 OK` با `status: "completed"`
```json
{
  "document_id": "<uuid>",
  "status": "completed",
  "progress": 100,
  "tasks": [
    {"task_type": "extract", "status": "completed", "progress": 100, "error_message": null},
    {"task_type": "chunk", "status": "completed", "progress": 100, "error_message": null}
  ]
}
```

> اگر هنوز `processing` هست، چند ثانیه دیگه صبر کن و دوباره بزن.

### گام 1.4: شروع Embedding

```bash
curl -X POST "http://localhost:8000/documents/$DOCUMENT_ID/embed/" \
  -H "Authorization: Bearer $TOKEN"
```

**خروجی مورد انتظار:** کد `202 Accepted`
```json
{
  "task_id": "uuid-task-id",
  "task_type": "embed",
  "status": "pending",
  "document_id": "<uuid>",
  "total_chunks": 3
}
```

> `total_chunks` تعداد chunkهایی را نشان می‌دهد که هنوز embedding ندارند.

**`TASK_ID` رو ذخیره کن:**
```bash
TASK_ID="<task_id_از_خروجی_بالا>"
```

### گام 1.5: پیگیری وضعیت Task Embedding



```bash
# بعد از چند ثانیه (بسته به OpenAI API speed)
sleep 10
curl -X GET "http://localhost:8000/tasks/$TASK_ID/" \
  -H "Authorization: Bearer $TOKEN"
```

**خروجی مورد انتظار (در حال اجرا):**
```json
{
  "id": "<task_id>",
  "document_id": "<document_id>",
  "task_type": "embed",
  "status": "running",
  "progress": 50,
  "result": null,
  "error_message": null,
  "started_at": "2026-04-27T...",
  "completed_at": null
}
```

**خروجی مورد انتظار (پس از اتمام):**
```json
{
  "id": "<task_id>",
  "document_id": "<document_id>",
  "task_type": "embed",
  "status": "completed",
  "progress": 100,
  "result": null,
  "error_message": null,
  "started_at": "2026-04-27T...",
  "completed_at": "2026-04-27T..."
}
```

### گام 1.6: تأیید ذخیره‌سازی embeddingها در دیتابیس

```bash
# وارد shell جنگو شو
docker-compose exec backend python manage.py shell
```

```python
from documents.models import Document, DocumentChunk
import numpy as np

doc = Document.objects.get(id="<DOCUMENT_ID>")
chunks = DocumentChunk.objects.filter(document=doc).order_by("chunk_index")

print(f"Document: {doc.title}")
print(f"Total chunks: {chunks.count()}")
print()

for c in chunks:
    has_embedding = c.embedding is not None
    emb_len = len(c.embedding) if has_embedding else 0
    print(f"  Chunk {c.chunk_index}: embedding={'✅' if has_embedding else '❌'} ({emb_len} dims)")
    print(f"    Content: {c.content[:80]}...")

# بررسی اینکه همه embeddingها 1536 بعدی هستند
all_valid = all(
    c.embedding is not None and len(c.embedding) == 1536
    for c in chunks
)
print(f"\nAll chunks have valid 1536-dim embeddings: {'✅ YES' if all_valid else '❌ NO'}")
```

```python
exit()
```

**خروجی مورد انتظار:**
- همه chunkها `✅` داشته باشند
- ابعاد همه `1536` باشد
- `All chunks have valid 1536-dim embeddings: ✅ YES`

---

## سناریو 2: تست وضعیت Task (TaskStatusView)

### گام 2.1: Task معتبر

```bash
# از TASK_ID که در سناریو 1 ذخیره کردی استفاده کن
curl -X GET "http://localhost:8000/tasks/$TASK_ID/" \
  -H "Authorization: Bearer $TOKEN"
```

✅ باید `200 OK` برگرداند با اطلاعات task.

### گام 2.2: Task نامعتبر (404)

```bash
curl -X GET "http://localhost:8000/tasks/00000000-0000-0000-0000-000000000000/" \
  -H "Authorization: Bearer $TOKEN"
```

✅ باید `404 Not Found` برگرداند:
```json
{"error": "not_found", "message": "Task not found"}
```

### گام 2.3: Task متعلق به کاربر دیگر (403)

> برای این تست باید یک کاربر دوم ثبت‌نام کنی و با توکن اون درخواست بدی.

```bash
# ثبت‌نام کاربر دوم
curl -X POST http://localhost:8000/auth/register/ \
  -H "Content-Type: application/json" \
  -d '{
    "email": "user2@example.com",
    "password": "testpass123",
    "full_name": "User Two"
  }'
```

```bash
TOKEN2="<accessToken_کاربر_دوم>"

# با توکن کاربر دوم، task کاربر اول رو ببین
curl -X GET "http://localhost:8000/tasks/$TASK_ID/" \
  -H "Authorization: Bearer $TOKEN2"
```

✅ باید `403 Forbidden` برگرداند:
```json
{"error": "permission_denied", "message": "You do not have permission to view this task."}
```

### گام 2.4: بدون احراز هویت (401)

```bash
curl -X GET "http://localhost:8000/tasks/$TASK_ID/"
```

✅ باید `401 Unauthorized` برگرداند:
```json
{"detail": "Authentication credentials were not provided."}
```

---

## سناریو 3: تست Batch Embedding

این سناریو به شما اجازه می‌دهد چند chunk خاص را بدون نیاز به document کامل، embedding کنید.

### گام 3.1: گرفتن chunk_idها

```bash
# لیست chunkهای یک سند رو بگیر
curl -X GET "http://localhost:8000/documents/$DOCUMENT_ID/chunks/" \
  -H "Authorization: Bearer $TOKEN"
```

**خروجی مورد انتظار:** کد `200 OK`
```json
{
  "count": 3,
  "results": [
    {"id": "chunk-uuid-1", "chunk_index": 0, "content": "...", ...},
    {"id": "chunk-uuid-2", "chunk_index": 1, "content": "...", ...},
    {"id": "chunk-uuid-3", "chunk_index": 2, "content": "...", ...}
  ]
}
```

### گام 3.2: Batch Embedding (برای chunkهایی که embedding ندارند)

> **نکته:** اگر قبلاً در سناریو 1 embedding انجام دادی، اول باید embedding بعضی chunkها رو پاک کنی تا این تست معنی داشته باشد. یا از یک سند جدید استفاده کن که هنوز embedding نشده.

```bash
# فرض کن می‌خوای دو chunk خاص رو embedding کنی
CHUNK_ID_1="<chunk-uuid-1>"
CHUNK_ID_2="<chunk-uuid-2>"

curl -X POST "http://localhost:8000/documents/chunks/batch-embed/" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"chunk_ids\": [\"$CHUNK_ID_1\", \"$CHUNK_ID_2\"]}"
```

**خروجی مورد انتظار:** کد `200 OK`
```json
{
  "processed": 2,
  "skipped": 0,
  "failed": 0
}
```

### گام 3.3: تست Skip — chunkهایی که قبلاً embedding شده‌اند

```bash
# دوباره همون درخواست رو بزن
curl -X POST "http://localhost:8000/documents/chunks/batch-embed/" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"chunk_ids\": [\"$CHUNK_ID_1\", \"$CHUNK_ID_2\"]}"
```

✅ باید `skipped: 2` برگرداند چون embedding از قبل وجود دارد:
```json
{
  "processed": 0,
  "skipped": 2,
  "failed": 0
}
```

### گام 3.4: تست Validation — chunk_ids نامعتبر

```bash
# ارسال رشته به جای آرایه
curl -X POST "http://localhost:8000/documents/chunks/batch-embed/" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"chunk_ids": "not-an-array"}'
```

✅ باید `400 Bad Request` برگرداند:
```json
{
  "error": "validation_error",
  "message": "Invalid request data",
  "details": {
    "chunk_ids": ["Expected a list of items but got type \"str\""]
  }
}
```

---

## سناریو 4: تست Re-embed

این سناریو بررسی می‌کند که آیا می‌توان embedding یک chunk خاص را بازتولید (جایگزین) کرد.

### گام 4.1: Re-embed یک chunk

```bash
curl -X POST "http://localhost:8000/documents/chunks/$CHUNK_ID_1/re-embed/" \
  -H "Authorization: Bearer $TOKEN"
```

**خروجی مورد انتظار:** کد `200 OK`
```json
{
  "chunk_id": "<chunk-uuid-1>",
  "embedding_updated": true
}
```

### گام 4.2: تست 404 — chunk نامعتبر

```bash
curl -X POST "http://localhost:8000/documents/chunks/00000000-0000-0000-0000-000000000000/re-embed/" \
  -H "Authorization: Bearer $TOKEN"
```

✅ باید `404 Not Found` برگرداند:
```json
{"error": "not_found", "message": "Chunk not found"}
```

### گام 4.3: تست 403 — chunk متعلق به کاربر دیگر

```bash
# با توکن کاربر دوم درخواست بده
curl -X POST "http://localhost:8000/documents/chunks/$CHUNK_ID_1/re-embed/" \
  -H "Authorization: Bearer $TOKEN2"
```

✅ باید `403 Forbidden` برگرداند:
```json
{"error": "permission_denied", "message": "You do not have permission to re-embed this chunk."}
```

---

## سناریو 5: تست خطاهای جامع (Error Scenarios)

### 5.1: Document Embed — 404 (سند نامعتبر)

```bash
curl -X POST "http://localhost:8000/documents/00000000-0000-0000-0000-000000000000/embed/" \
  -H "Authorization: Bearer $TOKEN"
```

✅ باید `404 Not Found` برگرداند.

### 5.2: Document Embed — 403 (سند متعلق به کاربر دیگر)

```bash
curl -X POST "http://localhost:8000/documents/$DOCUMENT_ID/embed/" \
  -H "Authorization: Bearer $TOKEN2"
```

✅ باید `403 Forbidden` برگرداند.

### 5.3: Document Embed — 401 (بدون توکن)

```bash
curl -X POST "http://localhost:8000/documents/$DOCUMENT_ID/embed/"
```

✅ باید `401 Unauthorized` برگرداند.

### 5.4: همه اندپوینت‌ها بدون احراز هویت

```bash
# GET /tasks/{id} بدون توکن
curl -X GET "http://localhost:8000/tasks/$TASK_ID/"

# POST /chunks/batch-embed بدون توکن
curl -X POST "http://localhost:8000/documents/chunks/batch-embed/" \
  -H "Content-Type: application/json" \
  -d "{\"chunk_ids\": [\"$CHUNK_ID_1\"]}"

# POST /chunks/{id}/re-embed بدون توکن
curl -X POST "http://localhost:8000/documents/chunks/$CHUNK_ID_1/re-embed/"
```

✅ همه باید `401 Unauthorized` برگردانند.

---

## سناریو 6: تست Re-embed Script

این اسکریپت همه embeddingهای موجود را پاک کرده و دوباره تولید می‌کند.

> **⚠️ هشدار:** این اسکریپت همه embeddingهای دیتابیس را پاک می‌کند. فقط در محیط توسعه (development) اجرا کن.

```bash
# اجرای اسکریپت reembed_all
docker-compose exec backend python scripts/reembed_all.py
```

**خروجی مورد انتظار:**
```
[reembed_all] Starting re-embed of all document chunks
[reembed_all] Found X chunks to re-embed
[reembed_all] Cleared embeddings for X chunks
[reembed_all] Scanning chunks... 500/X (XX%)
[reembed_all] Collected Y unique documents from X chunks
[reembed_all] Queued re-embed for document <uuid> (task=<uuid>)
[reembed_all] Re-embedding complete: Y documents queued, 0 failed (X total chunks)
```

### تأیید بعد از اجرای اسکریپت:

```bash
# بعد از چند ثانیه (بسته به تعداد chunkها)
sleep 15

# بررسی وضعیت یک task
# اول task_idها رو از دیتابیس پیدا کن
docker-compose exec backend python manage.py shell
```

```python
from tasks.models import ProcessingTask

tasks = ProcessingTask.objects.filter(
    task_type="embed"
).order_by("-created_at")[:5]

for t in tasks:
    print(f"Task {t.id}: status={t.status}, progress={t.progress}, "
          f"error={t.error_message}")
```

```python
exit()
```

✅ باید همه taskها `status=completed` و `progress=100` داشته باشند.

---

## سناریو 7: تست pgvector Index Verification

این سناریو بررسی می‌کند که ایندکس ivfflat روی ستون `embedding` وجود دارد.

### گام 7.1: اجرای system check

```bash
docker-compose exec backend python manage.py check
```

**خروجی مورد انتظار:** بدون هیچ خطای `documents.E001` تا `E004`:
```
System check identified no issues (0 silenced).
```

### گام 7.2: بررسی مستقیم ایندکس در PostgreSQL

```bash
# اتصال به دیتابیس
docker-compose exec postgres psql -U docuchat_user -d docuchat_db
```

```sql
-- بررسی وجود extension vector
SELECT * FROM pg_extension WHERE extname = 'vector';

-- بررسی وجود ایندکس ivfflat
SELECT indexname, indexdef 
FROM pg_indexes 
WHERE tablename = 'document_chunks' 
  AND indexname = 'idx_chunks_embedding';
```

**خروجی مورد انتظار:**
```
extname | extowner | extnamespace | extrelocatable | extversion
---------+----------+--------------+----------------+------------
 vector  |       10 |         2200 | f              | 0.8.0

      indexname      |                                                      indexdef
---------------------+----------------------------------------------------------------------------------------------------------------------
 idx_chunks_embedding | CREATE INDEX idx_chunks_embedding ON document_chunks USING ivfflat (embedding vector_cosine_ops) WITH (lists=100)
```

```sql
\q
```

### گام 7.3: تست خودکار pgvector checks

```bash
docker-compose exec backend python manage.py test documents.tests.test_pgvector_checks
```

✅ باید همه تست‌ها پاس شوند:
```
...
----------------------------------------------------------------------
Ran X tests in X.XXXs
OK
```

---

## سناریو 8 (اختیاری): تست End-to-End با یک فایل PDF واقعی

اگر یک فایل PDF واقعی (چند صفحه‌ای) داری، می‌تونی سناریوی کامل رو با اون تست کنی:

```bash
# آپلود فایل PDF واقعی
curl -X POST http://localhost:8000/documents/upload/ \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@/path/to/real-document.pdf"

DOCUMENT_ID_REAL="<uuid>"

# پردازش
curl -X POST "http://localhost:8000/documents/$DOCUMENT_ID_REAL/process/" \
  -H "Authorization: Bearer $TOKEN"

# صبر کن (برای فایل بزرگتر، زمان بیشتری نیازه)
sleep 15

# بررسی وضعیت
curl -X GET "http://localhost:8000/documents/$DOCUMENT_ID_REAL/processing-status/" \
  -H "Authorization: Bearer $TOKEN"

# Embedding
curl -X POST "http://localhost:8000/documents/$DOCUMENT_ID_REAL/embed/" \
  -H "Authorization: Bearer $TOKEN"

# صبر کن (بسته به تعداد chunkها)
sleep 30

# بررسی وضعیت task
# اول task_id رو از processing-status ببین
```

---

## اجرای تست‌های خودکار (Automated Tests)

علاوه بر تست دستی، تست‌های خودکار رو هم اجرا کن:

```bash
# تست‌های اختصاصی embedding
docker-compose exec backend python manage.py test documents.tests.test_embedding

# تست‌های pgvector checks
docker-compose exec backend python manage.py test documents.tests.test_pgvector_checks

# همه تست‌های documents
docker-compose exec backend python manage.py test documents.tests

# همه تست‌های پروژه
docker-compose exec backend pytest
```

---

## عیب‌یابی (Troubleshooting)

| مشکل | راه‌حل |
|------|--------|
| `401 Unauthorized` | توکن منقضی شده. دوباره لاگین کن و توکن جدید بگیر. |
| Task همیشه `pending` می‌مونه | چک کن `celery_worker` در حال اجراست: `docker-compose ps celery_worker` |
| `OpenAI API key not configured` | چک کن `OPENAI_API_KEY` در فایل `.env` تنظیم شده |
| `embedding` همیشه `null` | چک کن `celery_worker` لاگ‌ها: `docker-compose logs celery_worker` |
| ایندکس pgvector وجود ندارد | migration 0004 رو اجرا کن: `docker-compose exec backend python manage.py migrate` |
| خطای `relation "vector" does not exist` | چک کن postgres از image `pgvector/pgvector:pg16` استفاده می‌کنه |

### مشاهده لاگ‌ها

```bash
# لاگ‌های celery worker (برای دیدن خطاهای OpenAI)
docker-compose logs celery_worker

# لاگ‌های backend
docker-compose logs backend

# دنبال کردن لاگ‌ها (tail -f)
docker-compose logs -f celery_worker
```

---

## خلاصه سناریوهای تست

| سناریو | اندپوینت | کد موفق | کد خطا |
|--------|----------|---------|--------|
| 1. آپلود + پردازش + Embedding | `POST /documents/{id}/embed/` | `202` | `404`, `403`, `401` |
| 2. وضعیت Task | `GET /tasks/{task_id}/` | `200` | `404`, `403`, `401` |
| 3. Batch Embedding | `POST /chunks/batch-embed/` | `200` | `400`, `401` |
| 4. Re-embed | `POST /chunks/{id}/re-embed/` | `200` | `404`, `403`, `401` |
| 5. خطاهای جامع | همه | — | `404`, `403`, `401`, `400` |
| 6. Re-embed Script | `scripts/reembed_all.py` | `exit 0` | `exit 1` |
| 7. pgvector Index | `manage.py check` | `no issues` | `E001-E004` |
