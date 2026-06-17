# VLM Batch Extraction — Performance Optimization Plan

> **Problem:** 16-page PDF takes ~5 minutes because every page makes a separate VLM API call (~20s each).
>
> **Solution:** Batch multiple pages in a single VLM call using multi-image support + JPEG compression.

---

## Optimization 1: Multi-Page Batching (Highest Impact)

Send 4 pages in a single VLM API call using multi-image messages:

```python
# Before: 16 calls × 20s = 320s
for page in garbled_pages:
    result = service.extract_page(doc, page)

# After: 4 calls × 30s = 120s  (~3x faster)
results = service.extract_pages_batch(doc, garbled_pages, batch_size=4)
```

The API call sends multiple images in one message:
```
content: [
    { type: "image_url", image_url: { url: "data:image/jpeg;base64,..." } },  # Page 1
    { type: "image_url", image_url: { url: "data:image/jpeg;base64,..." } },  # Page 2
    { type: "image_url", image_url: { url: "data:image/jpeg;base64,..." } },  # Page 3
    { type: "image_url", image_url: { url: "data:image/jpeg;base64,..." } },  # Page 4
    { type: "text", text: "متن این ۴ صفحه را استخراج کن..." }
]
```

The VLM returns text with `[PAGE 1]`, `[PAGE 2]` markers which we parse.

## Optimization 2: JPEG Instead of PNG (High Impact)

PNG for text images is unnecessary. JPEG quality=85:
- PNG: ~200-500KB per page → large base64 → many tokens
- JPEG: ~30-80KB per page → 5-10x smaller → fewer tokens → faster API

## Optimization 3: Lower Default DPI (Medium Impact)

Change default DPI from 200 to 150:
- 150 DPI is still excellent for OCR (legal text at 150 DPI is very readable)
- Image area reduction: (150²/200²) = 56% of original size
- Combined with JPEG: ~10x size reduction

## Expected Results

| Metric | Before | After | Improvement |
|--------|--------|-------|-------------|
| 16-page document | 320s (~5 min) | ~80-120s (~1.5-2 min) | **~3-4x** |
| API calls for 16 pages | 16 | 4 | 4x fewer |
| Image size per page | ~300KB PNG | ~50KB JPEG | **6x smaller** |

## Files to Change

### 1. [`vision_extraction_service.py`](src/backend/documents/services/vision_extraction_service.py)

Add new method and batch prompt:

```python
_VLM_BATCH_PROMPT: str = """
شما یک استخراج‌کننده‌ی دقیق متن از تصویر هستید.

تعداد {count} تصویر از صفحات مختلف یک سند حقوقی به شما داده شده است.
برای هر صفحه، متن را دقیقاً استخراج کنید.

قوانین:
۱. هر صفحه را جداگانه استخراج کنید.
۲. قبل از متن هر صفحه، marker [PAGE X] را قرار دهید
   (مثال: [PAGE 1]\nمتن صفحه اول...\n\n[PAGE 2]\nمتن صفحه دوم...)
۳. متن را کلمه‌به‌کلمه و بدون تغییر استخراج کنید.
۴. اعداد و شماره مواد را دقیقاً حفظ کنید.
۵. فقط متن با markerهای [PAGE X] را برگردانید.
"""

def extract_pages_batch(
    self,
    pdf_document: fitz.Document,
    page_indices: list[int],
    batch_size: int = 4,
) -> dict[int, PageExtractionResult]:
    """Extract text from multiple pages in batches.
    
    Groups pages into batches, renders each batch as multi-image
    VLM calls, and parses the response.
    """
    results: dict[int, PageExtractionResult] = {}
    
    for i in range(0, len(page_indices), batch_size):
        batch = page_indices[i:i + batch_size]
        batch_results = self._extract_batch(pdf_document, batch)
        results.update(batch_results)
    
    return results

def _extract_batch(
    self, pdf_document: fitz.Document, batch: list[int]
) -> dict[int, PageExtractionResult]:
    # Render all pages in batch to JPEG
    images = []
    for idx in batch:
        page = pdf_document.load_page(idx)
        pix = page.get_pixmap(dpi=self.dpi)
        img_bytes = pix.tobytes("jpeg")  # JPEG!
        b64 = base64.b64encode(img_bytes).decode()
        images.append(f"data:image/jpeg;base64,{b64}")
    
    # Build multi-image content
    content = [
        {"type": "image_url", "image_url": {"url": img}}
        for img in images
    ]
    content.append({
        "type": "text",
        "text": _VLM_BATCH_PROMPT.format(count=len(batch))
    })
    
    # Single API call
    response = self._call_vlm_with_content(content)
    
    # Parse response
    page_texts = self._parse_batch_response(response, batch)
    
    # Build results
    results = {}
    for page_idx, text in zip(batch, page_texts):
        page_num = page_idx + 1
        verification = self._verify(text, page_num)
        results[page_num] = PageExtractionResult(
            page_num=page_num,
            text=text,
            source=self.model,
            quality_score=self._compute_output_quality(text),
            verified=verification.verified,
            verification_flags=verification.flags,
        )
    return results
```

Also update `extract_page()` to use JPEG (line 204):
```python
# Before:
img_bytes = pix.tobytes("png")
# After:
img_bytes = pix.tobytes("jpeg")
```

### 2. [`document_processing.py`](src/backend/documents/tasks/document_processing.py)

Update extraction loop to collect garbled pages and batch-process them:

```python
# Instead of per-page VLM call:
garbled_page_indices = []
for page_num in range(num_pages):
    # ... PyMuPDF extraction + quality check ...
    if is_garbled:
        garbled_page_indices.append(page_num)
        page_results.append(f"[PAGE {page_num + 1}]\n{text}")
    else:
        page_results.append(f"[PAGE {page_num + 1}]\n{text}")

# Batch-process all garbled pages
if garbled_page_indices and vision_enabled:
    vl_results = vision_service.extract_pages_batch(
        pdf_document, garbled_page_indices
    )
    # Replace garbled pages with VLM results
    for page_num_1based, result in vl_results.items():
        idx = page_num_1based - 1
        page_results[idx] = f"[PAGE {page_num_1based}]\n{result.text}"
        vl_page_count += 1
        if not result.verified:
            unverified_pages.append({
                "page": page_num_1based,
                "flags": result.verification_flags,
            })
```

### 3. [`settings.py`](src/backend/config/settings.py)

Lower default DPI:
```python
VISION_EXTRACTION_DPI = env.int('VISION_EXTRACTION_DPI', default=150)
```
