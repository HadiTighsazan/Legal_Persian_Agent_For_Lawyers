# Manual Test Guide: Task 4 + Task 5 — Document Processing Pipeline

## پیش‌نیازها

- داکر در حال اجراست (`docker-compose up -d`)
- یک کاربر ثبت‌نام شده و توکن JWT معتبر دارید

---

## مرحله 0: بررسی وضعیت سرویس‌ها

```bash
# توی ترمینال گیت بش (در مسیر پروژه):
cd /c/Users/hadit/Desktop/rag-project

# ببین سرویس‌ها بالاست یا نه
docker-compose ps
```

باید `backend`، `frontend`، `db`، `redis`، `celery_worker` رو `Up` ببینی.

---

## مرحله 1: ثبت‌نام و دریافت توکن

```bash
# ثبت‌نام کاربر جدید
curl -X POST http://localhost:8000/auth/register/ \
  -H "Content-Type: application/json" \
  -d '{
    "email": "test@example.com",
    "password": "testpass123",
    "full_name": "Test User"
  }'
```

**خروجی مورد انتظار:** کد `201 Created` با `accessToken` و `refreshToken`.

> **نکته:** اگر از قبل کاربر داری، می‌تونی از لاگین استفاده کنی:
> ```bash
> curl -X POST http://localhost:8000/auth/login/ \
>   -H "Content-Type: application/json" \
>   -d '{"email": "test@example.com", "password": "testpass123"}'
> ```

**توکن رو ذخیره کن.** بعداً بهش نیاز داری. بذارش توی یک متغیر:

```bash
TOKEN="<accessToken_اینجا_بذار>"
```

---

## مرحله 2: آپلود فایل

اول یک فایل PDF تستی درست کن:

```bash
# یک فایل PDF ساده با PowerShell بساز
powershell -Command "echo 'Hello World from test document!' | Out-File -FilePath /tmp/test-doc.txt -Encoding utf8"
```

> **توجه:** برای آپلود باید حتماً یک فایل PDF واقعی داشته باشی. اگه PDF نداری، از مسیر پروژه یک فایل متنی ساده با پسوند `.pdf` بساز:
> ```bash
> echo "This is a test PDF content for document processing pipeline testing." > /tmp/test-doc.pdf
> ```

حالا آپلود کن:

```bash
curl -X POST http://localhost:8000/documents/upload/ \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@/tmp/test-doc.pdf"
```

**خروجی مورد انتظار:** کد `201 Created` با اطلاعات document شامل `id`.

```json
{
  "id": "uuid-اینجا",
  "title": "...",
  "original_filename": "test-doc.pdf",
  "file_size": ...,
  "mime_type": "application/pdf",
  "file_path": "...",
  "storage_type": "local",
  "status": "uploaded",
  "created_at": "..."
}
```

**`DOCUMENT_ID` رو ذخیره کن:**

```bash
DOCUMENT_ID="<uuid_اینجا_بذار>"
```

---

## مرحله 3: شروع پردازش (Task 5 — Process Endpoint)

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

### تست خطاها:

**تست 404 — سند نامعتبر:**
```bash
curl -X POST "http://localhost:8000/documents/00000000-0000-0000-0000-000000000000/process/" \
  -H "Authorization: Bearer $TOKEN"
```
✅ باید `404 Not Found` برگردونه.

**تست 403 — سند متعلق به کاربر دیگه:**
> برای این تست باید یک کاربر دوم ثبت‌نام کنی و با توکن اون درخواست بدی.

**تست 400 — پردازش تکراری:**
> همون دستور اول رو دوباره بزن. باید `400 Bad Request` برگردونه با پیام "already being processed".

---

## مرحله 4: بررسی وضعیت پردازش (Task 5 — Status Endpoint)

```bash
curl -X GET "http://localhost:8000/documents/$DOCUMENT_ID/processing-status/" \
  -H "Authorization: Bearer $TOKEN"
```

**خروجی مورد انتظار (بعد از چند ثانیه):** کد `200 OK`

```json
{
  "document_id": "<uuid>",
  "status": "completed",
  "progress": 100,
  "tasks": [
    {
      "task_type": "extract",
      "status": "completed",
      "progress": 100,
      "error_message": null
    },
    {
      "task_type": "chunk",
      "status": "completed",
      "progress": 100,
      "error_message": null
    }
  ]
}
```

> **نکته:** اگه بلافاصله بعد از مرحله 3 این دستور رو بزنی، احتمالاً `status: "processing"` و `progress` کمتر از 100 می‌بینی. این طبیعیه — چند لحظه صبر کن و دوباره بزن.

### تست خطاها:

**تست 404:**
```bash
curl -X GET "http://localhost:8000/documents/00000000-0000-0000-0000-000000000000/processing-status/" \
  -H "Authorization: Bearer $TOKEN"
```
✅ باید `404 Not Found` برگردونه.

**تست 403:**
> با توکن کاربر دوم درخواست بده به سند کاربر اول.

**تست 401 — بدون احراز هویت:**
```bash
curl -X GET "http://localhost:8000/documents/$DOCUMENT_ID/processing-status/"
```
✅ باید `401 Unauthorized` برگردونه.

---

## مرحله 5: بررسی Chunkهای ایجاد شده (تأیید Task 4)

```bash
# برو داخل کانتینر backend
docker-compose exec backend python manage.py shell
```

حالا توی shell این دستورات رو بزن:

```python
from documents.models import Document, DocumentChunk

doc = Document.objects.get(id="<DOCUMENT_ID>")
print(f"Status: {doc.status}")
print(f"Processing status: {doc.processing_status}")
print(f"Total pages: {doc.total_pages}")
print(f"Total chunks: {doc.total_chunks}")
print(f"Extracted text length: {doc.extracted_text_length}")

chunks = DocumentChunk.objects.filter(document=doc).order_by("chunk_index")
print(f"\nNumber of chunks: {chunks.count()}")
for c in chunks:
    print(f"  Chunk {c.chunk_index}: pages {c.page_start}-{c.page_end}, {c.token_count} tokens")
    print(f"    Content preview: {c.content[:100]}...")
```

**خروجی مورد انتظار:**
- `processing_status` = `completed`
- `total_chunks` > 0
- Chunkها با `chunk_index` ترتیبی و محتوای متنی

از shell خارج شو:
```python
exit()
```

---

## مرحله 6: تست سناریوی خطا — فایل خراب

اگه می‌خوای سناریوی خطا رو هم تست کنی:

```bash
# یک فایل خراب (غیر PDF) آپلود کن
echo "this is not a pdf" > /tmp/corrupted.pdf

curl -X POST http://localhost:8000/documents/upload/ \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@/tmp/corrupted.pdf"
```

`DOCUMENT_ID` رو ذخیره کن و بعد پردازش رو شروع کن:

```bash
curl -X POST "http://localhost:8000/documents/$DOCUMENT_ID/process/" \
  -H "Authorization: Bearer $TOKEN"
```

بعد از چند ثانیه وضعیت رو چک کن:

```bash
curl -X GET "http://localhost:8000/documents/$DOCUMENT_ID/processing-status/" \
  -H "Authorization: Bearer $TOKEN"
```

✅ باید `status: "failed"` و `error_message` مربوط به "corrupted" رو ببینی.

---

## مرحله 7: اجرای تست‌های خودکار (اختیاری)

برای اجرای تست‌های unit مربوط به Task 4 و 5:

```bash
# تست views
docker-compose exec backend python manage.py test documents.tests.test_views

# تست tasks
docker-compose exec backend python manage.py test documents.tests.test_tasks

# تست serializers
docker-compose exec backend python manage.py test documents.tests.test_serializers

# یا همه با هم
docker-compose exec backend python manage.py test documents.tests
```

---

## خلاصه سناریوهای تست

| مرحله | دستور | کد مورد انتظار |
|-------|-------|-----------------|
| ثبت‌نام | `POST /auth/register/` | `201` |
| آپلود | `POST /documents/upload/` | `201` |
| شروع پردازش | `POST /documents/{id}/process/` | `202` |
| وضعیت پردازش | `GET /documents/{id}/processing-status/` | `200` |
| سند نامعتبر | `POST /documents/{id}/process/` | `404` |
| بدون احراز | `POST /documents/{id}/process/` | `401` |
| سند دیگران | `POST /documents/{id}/process/` | `403` |
| پردازش تکراری | `POST /documents/{id}/process/` (دوباره) | `400` |
| فایل خراب | آپلود + پردازش + وضعیت | `failed` |

---

## نکات مهم

1. **تایمینگ:** بین شروع پردازش و چک وضعیت چند ثانیه صبر کن تا Celery worker فرصت اجرا داشته باشه.
2. **لاگ‌ها:** اگه خطایی دیدی، لاگ‌های backend رو چک کن:
   ```bash
   docker-compose logs backend
   docker-compose logs celery_worker
   ```
3. **توکن:** توکن JWT بعد از مدتی منقضی می‌شه. اگه خطای `401` گرفتی، دوباره لاگین کن و توکن جدید بگیر.
4. **فایل PDF:** اگه فایل PDF واقعی نداری، یه فایل متنی ساده با پسوند `.pdf` هم کار می‌کنه برای تست (البته extraction خروجی معنی‌داری نخواهد داشت).
