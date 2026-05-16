# گزارش نمونه کار — DocuChat: سامانه پرسش و پاسخ هوشمند اسناد حقوقی فارسی

> **پروژه:** سامانه RAG (Retrieval-Augmented Generation) برای متون حقوقی فارسی  
> **نقش:** توسعه‌دهنده بک‌اند (Django, Django REST Framework, PostgreSQL/pgvector, Celery, Docker)  
> **وضعیت:** فاز ۱ کامل ✅ — فاز ۲ کامل ✅ 🔄

---

## ۱. معرفی پروژه

**DocuChat** یک سامانه هوشمند پرسش و پاسخ حقوقی است که به کاربران امکان می‌دهد اسناد حقوقی فارسی (قراردادها، آرای قضایی، قوانین مصوب) را آپلود کرده و سوالات خود را به زبان فارسی بپرسند. سیستم با استفاده از معماری **RAG (Retrieval-Augmented Generation)**، محتوای مرتبط را از اسناد بازیابی کرده و پاسخ‌های دقیق با استناد به منابع تولید می‌کند.

پروژه در دو فاز اصلی طراحی شده:

| فاز | عنوان | وضعیت |
|-----|-------|--------|
| **فاز ۱** | Local RAG — دستیار خوانش اسناد | ✅ کامل |
| **فاز ۲** | Global RAG — پژوهشگر حقوقی | 🔄 در حال اجرا |

### ارزش تجاری پروژه

- **جایگزینی جستجوی دستی** در قوانین و آرای قضایی با جستجوی هوشمند ترکیبی
- **صرفه‌جویی زمانی** برای وکلا، قضات و پژوهشگران حقوقی
- **دقت بالا** با استناد به منابع معتبر حقوقی (قوانین مصوب، آرای وحدت رویه، نظریات مشورتی)
- **قابلیت توسعه** به سامانه تحلیل پرونده و تولید اسناد حقوقی

---

## ۲. معماری فنی

### نمای کلی

```
┌─────────────────────────────────────────────────────────┐
│                    Nginx Reverse Proxy                    │
└──────────┬──────────────────────────────────┬────────────┘
           │                                  │
           ▼                                  ▼
┌─────────────────────┐          ┌─────────────────────┐
│   Django Backend    │          │  React + Vite       │
│   (Gunicorn)        │          │  Frontend           │
│   Port 8000         │          │  Port 5173          │
└──────┬──────┬───────┘          └─────────────────────┘
       │      │
       ▼      ▼
┌──────────┐ ┌──────────────────┐
│ PostgreSQL│ │     Redis        │
│ +pgvector │ │ (Cache + Broker) │
└──────────┘ └────────┬─────────┘
                      │
                      ▼
             ┌──────────────────┐
             │  Celery Worker   │
             │  (Async Tasks)   │
             └──────────────────┘
```

### استک فناوری

| لایه | فناوری | توضیح |
|------|--------|-------|
| **Backend** | Django 4.2 + Django REST Framework | API‌های RESTful با معماری ماژولار |
| **Database** | PostgreSQL 16 + pgvector | پایگاه داده با قابلیت جستجوی برداری |
| **Async Tasks** | Celery + Redis | پردازش اسناد در پس‌زمینه (استخراج متن، chunking، embedding) |
| **AI Providers** | OpenAI / Gemini / Ollama | پشتیبانی از چندین ارائه‌دهنده هوش مصنوعی |
| **Embedding** | bge-m3 (Ollama) / text-embedding-3-small | بردارهای ۱۰۲۴ بعدی برای جستجوی معنایی |
| **Frontend** | React + Vite + TailwindCSS + shadcn/ui | رابط کاربری مدرن و واکنش‌گرا |
| **DevOps** | Docker + Docker Compose + Nginx | استقرار کانتینری شده با ۷ سرویس |

---

## ۳. چالش‌های فنی و راه‌حل‌ها

### چالش ۱: جستجوی ترکیبی (Hybrid Search) برای متون حقوقی فارسی

**مشکل:** جستجوی صرفاً برداری (vector search) برای متون حقوقی فارسی کافی نیست، زیرا:
- اصطلاحات حقوقی تخصصی ممکن است در فضای برداری به خوبی تفکیک نشوند
- اعداد فارسی (۱۲۳) و انگلیسی (123) در متون حقوقی به صورت ترکیبی استفاده می‌شوند
- غلط‌های املایی و OCR در اسناد اسکن شده رایج است

**راه‌حل:** پیاده‌سازی **جستجوی ترکیبی سه‌گانه** با Fusion RRF:

```python
# hybrid_search() — ترکیب سه روش جستجو با Reciprocal Rank Fusion
results = _rrf_fusion_multi(
    [vector_results, keyword_results, trigram_results],
    k=60,  # ثابت RRF استاندارد
    weights=[3.0, 1.0, 1.0],  # وزن بیشتر برای جستجوی برداری
)
```

| روش جستجو | فناوری | کاربرد |
|-----------|--------|--------|
| **Vector Search** | pgvector `CosineDistance` | جستجوی معنایی با embedding |
| **Keyword Search** | PostgreSQL FTS (`tsvector` + GIN index) | تطابق دقیق کلمات کلیدی |
| **Trigram Search** | pg_trgm (`gin_trgm_ops`) | تطابق فازی برای غلط‌های املایی |

**فایل‌های مرتبط:**
- [`search_service.py`](src/backend/documents/services/search_service.py) — هسته جستجوی ترکیبی (۱۴۸۲ خط)
- [`persian_normalizer.py`](src/backend/documents/services/persian_normalizer.py) — نرمال‌سازی متن فارسی

---

### چالش ۲: پردازش اسناد حقوقی فارسی با ساختار پیچیده

**مشکل:** اسناد حقوقی فارسی دارای ساختار سلسله‌مراتبی پیچیده‌ای هستند (مواد، تبصره‌ها، بندها، فصول) و استخراج صحیح این ساختار برای chunking مؤثر ضروری است.

**راه‌حل:** توسعه **Legal Structure Detector** که به صورت خودکار ساختار اسناد حقوقی را تشخیص می‌دهد:

```python
# تشخیص خودکار ساختار حقوقی
detector = LegalStructureDetector()
structure = detector.detect(text)
# خروجی: [{"type": "article", "number": "1", "content": "..."}, ...]
```

**ویژگی‌های کلیدی:**
- تشخیص الگوهای رایج فارسی: «ماده», «تبصره», «بند», «فصل»
- استخراج اعداد به هر دو формаت فارسی و انگلیسی
- حفظ یکپارچگی قانونی (هر ماده به صورت کامل در یک chunk باقی می‌ماند)
- پشتیبانی از overlap هوشمند در مرزهای بندها

**فایل‌های مرتبط:**
- [`chunking_service.py`](src/backend/documents/services/chunking_service.py) — سرویس chunking با تشخیص ساختار حقوقی
- [`legal_structure_detector.py`](src/backend/documents/services/legal_structure_detector.py) — تشخیص ساختار اسناد حقوقی

---

### چالش ۳: معماری RAG سراسری (Global RAG) با سه هاب حقوقی

**مشکل:** کاربران نیاز به جستجو در سه منبع مجزای حقوقی دارند:
1. **قوانین مصوب** (Legislation) — ~۱۰ قانون
2. **رویه‌های قضایی** (Judicial Precedent) — صدها رأی
3. **نظریات مشورتی** (Advisory Opinions) — هزاران نظر

این سه منبع ساختار، حجم و ماهیت متفاوتی دارند.

**راه‌حل:** معماری **Question Router + Multi-Hub Search + Synthesis**:

```
سوال کاربر
    │
    ▼
┌──────────────────────────────┐
│  Question Router (LLM)       │  ← تحلیل سوال و تعیین هاب‌های مرتبط
│  تجزیه سوال به زیر-پرسش‌ها   │     تولید FTS + Vector query برای هر هاب
└──────────┬───────────────────┘
           │
           ▼
    ┌──────┴──────┐
    ▼             ▼             ▼
┌─────────┐ ┌─────────┐ ┌─────────┐
│قوانین   │ │رویه‌های │ │نظریات   │
│مصوب     │ │قضایی    │ │مشورتی   │
│hybrid_  │ │hybrid_  │ │hybrid_  │
│search() │ │search() │ │search() │
└────┬────┘ └────┬────┘ └────┬────┘
     │           │           │
     ▼           ▼           ▼
┌──────────────────────────────┐
│  Multi-Source Context Builder│  ← برچسب‌گذاری chunks با هاب + سند
└──────────┬───────────────────┘
           │
           ▼
┌──────────────────────────────┐
│  LLM Synthesis               │  ← فاز ۲b: پاسخ جزئی per-hub + سنتز
│  تشخیص تعارض بین هاب‌ها      │     با رعایت سلسله‌مراتب حقوقی
└──────────┬───────────────────┘
           │
           ▼
    پاسخ نهایی + استناد + گزارش تعارض
```

**فایل‌های مرتبط:**
- [`global_rag_service.py`](src/backend/conversations/global_rag_service.py) — سرویس اصلی RAG سراسری (۱۱۰۳ خط)
- [`question_router.py`](src/backend/conversations/question_router.py) — مسیریاب سوالات با LLM (۴۸۷ خط)
- [`query_formulation.py`](src/backend/conversations/query_formulation.py) — فرمول‌سازی HyDE (۳۹۱ خط)

---

### چالش ۴: نرمال‌سازی متن فارسی برای FTS

**مشکل:** PostgreSQL FTS با پیکربندی `simple` از اعداد فارسی پشتیبانی نمی‌کند. اگر کاربر جستجوی «ماده ۲۲» را انجام دهد اما متن سند حاوی «ماده 22» باشد (یا برعکس)، جستجو نتیجه‌ای برنمی‌گرداند.

**راه‌حل:** پیاده‌سازی **PersianNormalizer** با قابلیت‌های زیر:

```python
class PersianNormalizer:
    @staticmethod
    def normalize_for_fts(text: str) -> str:
        text = unicodedata.normalize('NFKC', text)  # تبدیل حروف عربی به فارسی
        text = ArabicToPersianConverter.convert(text)  # ی منقوطه → ی
        text = DigitNormalizer.normalize(text)  # ۱۲۳ → 123
        text = PresentationFormNormalizer.normalize(text)  # اشکال نمایشی عربی
        return text
```

**فایل مرتبط:**
- [`persian_normalizer.py`](src/backend/documents/services/persian_normalizer.py)

---

### چالش ۵: معماری Provider-Agnostic برای AI/LLM

**مشکل:** وابستگی به یک ارائه‌دهنده خاص هوش مصنوعی ریسک دارد (قطع سرویس، تغییر قیمت، تحریم‌ها). سیستم باید قابلیت جابجایی بین OpenAI، Google Gemini و Ollama (محلی) را داشته باشد.

**راه‌حل:** پیاده‌سازی **Provider Registry Pattern** با واسط انتزاعی:

```python
# ثبت و استفاده از ارائه‌دهندگان به صورت پلاگین
register_embedding_provider("ollama", OllamaEmbeddingProvider)
register_embedding_provider("google", GeminiEmbeddingProvider)
register_embedding_provider("openai", OpenAIEmbeddingProvider)

# استفاده در زمان اجرا بر اساس تنظیمات
provider = get_embedding_provider()  # بر اساس settings.EMBEDDING_PROVIDER
embedding = provider.embed_query(text)
```

**فایل‌های مرتبط:**
- [`registry.py`](src/backend/providers/registry.py) — ثبات و کارخانه ارائه‌دهندگان
- [`base.py`](src/backend/providers/base.py) — کلاس‌های پایه انتزاعی
- [`ollama_embedding.py`](src/backend/providers/ollama_embedding.py) — ارائه‌دهنده محلی
- [`openai_embedding.py`](src/backend/providers/openai_embedding.py) — ارائه‌دهنده ابری
- [`gemini_embedding.py`](src/backend/providers/gemini_embedding.py) — ارائه‌دهنده ابری

---

### چالش ۶: پایپلاین پردازش اسناد ناهمزمان

**مشکل:** پردازش اسناد PDF (استخراج متن → chunking → embedding) ممکن است برای اسناد حجیم (تا ۵۰۰MB) چند دقیقه طول بکشد. این عملیات باید در پس‌زمینه انجام شود.

**راه‌حل:** پایپلاین Celery با ۳ مرحله:

```python
# زنجیره وظایف Celery
@pipeline_task
def extract_text_from_pdf(document_id): ...
@pipeline_task
def chunk_document(document_id): ...
@pipeline_task
def embed_document(document_id): ...

# اجرای زنجیره‌ای
chain = extract_text_from_pdf.s(doc_id) | chunk_document.s() | embed_document.s()
chain()
```

**ویژگی‌ها:**
- پیگیری وضعیت از طریق `ProcessingTask` مدل
- قابلیت Retry تا ۳ بار
- نمایش پیشرفت real-time از طریق API
- پشتیبانی از ۳ روش استخراج متن: PyMuPDF, pdfplumber, Tesseract OCR

**فایل‌های مرتبط:**
- [`documents/tasks.py`](src/backend/documents/tasks.py) — وظایف Celery
- [`processing_service.py`](src/backend/documents/services/processing_service.py) — سرویس مدیریت پایپلاین
- [`views.py`](src/backend/documents/views.py) — APIهای وضعیت پردازش

---

## ۴. دستاوردهای فنی کلیدی

### مدل داده

۸ جدول اصلی با روابط کامل و ایندکس‌های بهینه:

| جدول | رکوردها | توضیح |
|------|---------|-------|
| `users` | - | احراز هویت با JWT + Refresh Token Rotation |
| `documents` | - | اسناد آپلودی + مرجع با `hub_type` |
| `document_chunks` | **۱۸,۹۲۷** | تکه‌های متنی با embedding و metadata حقوقی |
| `conversations` | - | مکالمات با پشتیبانی از `document_id` nullable |
| `messages` | - | پیام‌ها با `sources` (JSONB) و `hub_metadata` |
| `processing_tasks` | - | پیگیری پایپلاین Celery |
| `api_keys` | - | کلیدهای API برای دسترسی برنامه‌نویسی |
| `refresh_tokens` | - | توکن‌های رفرش با قابلیت ابطال |

### ایندکس‌های تخصصی

- **GIN index** روی `search_vector` برای Full-Text Search
- **GIN index** با `gin_trgm_ops` روی `content` برای جستجوی فازی
- **IVFFlat index** روی `embedding` برای جستجوی برداری
- ایندکس‌های ترکیبی روی `hub_type`، `legal_status`، `law_name`، `approval_date`

### تست‌ها

- **بک‌اند:** بیش از ۷۵ تست با Pytest (مدل‌ها، ویوها، سرویس‌ها، middleware)
- **فرانت‌اند:** تست‌های Vitest برای استورها و API utilities
- **روش:** TDD (RED → GREEN → REFACTOR)

---

## ۵. معماری Docker

۷ سرویس کانتینری شده با Docker Compose:

```yaml
services:
  postgres:    # pgvector/pgvector:pg16
  redis:       # redis:7-alpine
  backend:     # Django + Gunicorn
  celery_worker:  # پردازش پس‌زمینه
  celery_beat:    # وظایف زمان‌بندی شده
  nginx:       # پروکسی معکوس
  frontend:    # React + Vite (توسعه)
```

**ویژگی‌ها:**
- Healthcheck برای تمام سرویس‌ها
- شبکه اختصاصی `docuchat_network`
- Volumeهای مجزا برای داده‌های ماندگار
- پشتیبانی از `host.docker.internal` برای اتصال به Ollama محلی

---

## ۶. نقش من در پروژه

به عنوان **توسعه‌دهنده بک‌اند**، مسئولیت‌های زیر را بر عهده داشته‌ام:

1. **طراحی معماری** — ساختار ماژولار Django با separation of concerns
2. **پیاده‌سازی RAG Pipeline** — جستجوی ترکیبی، HyDE query formulation، استخراج استناد
3. **Global RAG** — مسیریاب سوالات، جستجوی چند-هابی، سنتز پاسخ با تشخیص تعارض
4. **Provider Registry** — معماری پلاگین‌محور برای AI/LLM
5. **پایپلاین ناهمزمان** — Celery + Redis برای پردازش اسناد
6. **نرمال‌سازی فارسی** — PersianNormalizer برای FTS و جستجوی دقیق
7. **API Design** — RESTful endpoints با مستندات Swagger/ReDoc
8. **تست‌نویسی** — TDD با Pytest برای تمام لایه‌ها
9. **Dockerization** — کانتینری‌سازی کامل با ۷ سرویس

---

## ۷. مسیر آینده

| فاز | عنوان | وضعیت |
|-----|-------|--------|
| **فاز ۳** | Case Analyzer — تحلیل‌گر پرونده | 📋 برنامه‌ریزی شده |
| **فاز ۴** | Legal Drafter — تولیدکننده اسناد حقوقی | 📋 برنامه‌ریزی شده |

**فاز ۳** قابلیت آپلود یک پرونده حقوقی و تحلیل آن در برابر کل دانش حقوقی سیستم را فراهم می‌کند (تشخیص ادعاها، تطابق با قوانین، شناسایی تعارض‌ها).

**فاز ۴** به کاربر امکان می‌دهد اسناد حقوقی جدید (قرارداد، دادخواست، لایحه) را با هوش مصنوعی و با استناد به قوانین معتبر تولید کند.

---

## ۸. لینک‌های مرتبط

- [Roadmap کامل پروژه](docs/roadmap.md)
- [مشخصات پایگاه داده](docs/references/database-schema.md)
- [ثبت API endpoints](docs/references/api-registry.md)
- [docker-compose.yml](docker-compose.yml) — معماری کانتینری
