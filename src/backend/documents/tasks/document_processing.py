"""
Celery tasks for the document processing pipeline.

Provides two Celery tasks:
- ``extract_text_from_pdf`` — opens a PDF with PyMuPDF (RTL-aware), extracts text
  **per-page** with ``[PAGE N]`` markers. For garbled pages (broken /ToUnicode
  CMap in Persian PDFs), falls back to a Vision-Language Model (Qwen3 VL) via
  OpenRouter for page-level image-to-text extraction.

  This replaces the old multi-stage fallback chain (pdfplumber → Tesseract →
  EasyOCR) with a single, page-level, VLM-based fallback path.
- ``chunk_document`` — receives the extracted text, delegates to
  :class:`~documents.services.anchor_chunking_service.AnchorChunkingService`,
  and persists the resulting chunks via bulk create.

The orchestration function ``process_document`` has been moved to
:mod:`documents.services.processing_service` — it is a **regular Python function**
(not a Celery task) called directly from the API view. It is re-exported from
:mod:`documents.tasks` for backward compatibility.

.. note::
   The ``embed_document`` task has been moved to
   :mod:`documents.tasks.embedding_tasks` to avoid dual ``ProcessingTask``
   management. See that module for the current implementation.
"""

from __future__ import annotations

import io
import logging
import os
import tempfile
import traceback
from typing import Any, Optional

from celery import chain, shared_task
from django.conf import settings
from django.db import transaction, IntegrityError, OperationalError
from django.utils import timezone

import fitz  # PyMuPDF

from documents.models import Document, DocumentChunk
from documents.services.anchor_chunking_service import (
    AnchorChunkingService,
)
from documents.services.persian_legal_chunker import PersianLegalChunker
from documents.services.error_handler import (
    classify_pdf_error,
    fail_processing_task,
    log_milestone,
)
from documents.services.non_text_filter import NonTextChunkFilter
from documents.services.persian_normalizer import PersianNormalizer
from documents.services.vision_extraction_service import (
    VisionExtractionService,
)
from documents.storage import get_storage_backend
from tasks.models import ProcessingTask

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Persian Language Confidence Score — multi-signal quality assessment
# ---------------------------------------------------------------------------

# Persian stopwords (general + legal domain)
_PERSIAN_STOPWORDS: set = {
    "از", "به", "در", "با", "برای", "و", "که", "این", "آن", "را",
    "تا", "یا", "اما", "اگر", "البته", "باید", "شاید", "ممکن",
    "بعد", "قبل", "زیر", "روی", "بین", "درباره", "مثل", "مانند",
    "چون", "زیرا", "بنابراین", "پس", "خواهد", "می", "است", "شد",
    "شود", "شده", "دارد", "داشت", "کرد", "کند", "گفت", "دهد",
    "بود", "باشند", "باشد", "نیز", "هم", "حدود", "سایر", "غیر",
}

_LEGAL_STOPWORDS: set = {
    "دادگاه", "شعبه", "خواهان", "خوانده", "دادنامه", "پرونده",
    "کلاسه", "رأی", "حکم", "قانون", "ماده", "تبصره", "مصوب",
    "الزام", "محکوم", "مستند", "مستندات", "دلایل", "ادعا",
    "دعوی", "درخواست", "اعتراض", "تجدیدنظر", "فرجام", "وکالت",
    "وکیل", "مدعی", "منع", "قبول", "رد", "ابطال", "تنفیذ",
    "استرداد", "تامین", "خسارت", "هزینه", "دادرسی", "کارشناسی",
    "کارشناس", "رای", "شرح", "گردش", "کار", "مندرج", "ذیل",
}

# Combined stopword set for scoring
_ALL_PERSIAN_STOPWORDS: set = _PERSIAN_STOPWORDS | _LEGAL_STOPWORDS

# Comprehensive set of valid Persian bigrams.
# Derived from common Persian words, legal terminology, and general text patterns.
# This is used by _compute_bigram_plausibility to distinguish valid Persian text
# from garbled/RTL-reversed text. Garbled text produces unusual bigram pairs
# that rarely appear in natural Persian.
_VALID_PERSIAN_BIGRAMS: set = {
    # --- Common 2-letter bigrams ---
    "ان", "ها", "ای", "ده", "ور", "دا", "را", "با", "ما", "نا",
    "تا", "یا", "بر", "در", "که", "از", "به", "شد", "ود", "ند",
    "ین", "من", "کن", "تو", "رو", "گر", "تر", "ری", "می", "زی",
    "ست", "ار", "ام", "ته", "گی", "وا", "فت", "زد", "لا", "لی",
    "قی", "فی", "بی", "دی", "سی", "تی", "کی", "چی", "شی",
    "جو", "خو", "دو", "زو", "سو", "شو", "فو", "گو", "لو", "مو",
    "نو", "هو", "یو", "آز", "آش", "آم", "آو", "آی",
    "اف", "اک", "ال", "اه", "او", "ای", "آب", "آت", "آث",
    "اج", "اح", "اخ", "اد", "اذ", "ار", "از", "اس", "اش", "اص",
    "اط", "اع", "اغ", "اف", "اق", "ال", "ام", "ان", "اه", "او",
    "ای", "با", "بت", "بح", "بد", "بر", "بز", "بس", "بش", "بط",
    "بع", "بغ", "بق", "بل", "بن", "به", "بو", "بی", "پا", "پد",
    "پر", "پس", "پش", "پن", "پو", "پی", "تا", "تب", "تپ", "تت",
    "تج", "تح", "تخ", "تد", "تر", "تز", "تس", "تش", "تص", "تط",
    "تع", "تف", "تق", "تل", "تم", "تن", "ته", "تو", "تی", "ثا",
    "ثب", "ثت", "ثخ", "ثد", "ثر", "ثع", "ثف", "ثل", "ثم", "ثن",
    "ثه", "ثو", "ثی", "جا", "جب", "جت", "جث", "جد", "جر", "جز",
    "جس", "جش", "جع", "جف", "جل", "جم", "جن", "جه", "جو", "جی",
    "چا", "چپ", "چر", "چش", "چق", "چل", "چم", "چن", "چه", "چو",
    "چی", "حا", "حب", "حت", "حث", "حد", "حر", "حز", "حس", "حش",
    "حص", "حض", "حط", "حظ", "حف", "حق", "حل", "حم", "حن", "حو",
    "حی", "خا", "خب", "خت", "خد", "خر", "خز", "خش", "خص", "خط",
    "خف", "خل", "خم", "خن", "خو", "خی", "دا", "دب", "دت", "دث",
    "دد", "دخ", "در", "دز", "دس", "دش", "دع", "دف", "دق", "دل",
    "دم", "دن", "ده", "دو", "دی", "ذا", "ذب", "ذخ", "ذر", "ذع",
    "ذل", "ذم", "ذن", "ذه", "ذو", "ذی", "را", "رب", "رت", "رج",
    "رخ", "رد", "رز", "رس", "رش", "رض", "رط", "رف", "رق", "رک",
    "رم", "رن", "ره", "رو", "ری", "زا", "زب", "زت", "زد", "زر",
    "زع", "زف", "زل", "زم", "زن", "زه", "زو", "زی", "ژا", "ژر",
    "ژل", "ژن", "ژو", "ژی", "سا", "سب", "ست", "سج", "سخ", "سد",
    "سر", "سز", "سس", "سش", "سع", "سف", "سق", "سل", "سم", "سن",
    "سه", "سو", "سی", "شا", "شب", "شت", "شد", "شر", "شز", "شش",
    "شع", "شف", "شق", "شک", "شل", "شم", "شن", "شه", "شو", "شی",
    "صا", "صب", "صت", "صح", "صد", "صر", "صع", "صف", "صل", "صم",
    "صن", "صه", "صو", "صی", "ضا", "ضب", "ضد", "ضر", "ضع", "ضف",
    "ضل", "ضم", "ضن", "ضه", "ضو", "ضی", "طا", "طب", "طح", "طر",
    "طع", "طف", "طل", "طم", "طن", "طه", "طو", "طی", "ظا", "ظب",
    "ظر", "ظف", "ظل", "ظم", "ظن", "ظه", "ظو", "ظی", "عا", "عب",
    "عت", "عد", "عر", "عز", "عس", "عش", "عص", "عض", "عط", "عف",
    "عل", "عم", "عن", "عه", "عو", "عی", "غا", "غب", "غت", "غد",
    "غر", "غش", "غص", "غض", "غط", "غف", "غل", "غم", "غن", "غو",
    "غی", "فا", "فت", "فج", "فح", "فخ", "فد", "فر", "فز", "فس",
    "فش", "فص", "فض", "فط", "فع", "فف", "فق", "فل", "فم", "فن",
    "فه", "فو", "فی", "قا", "قب", "قت", "قد", "قر", "قز", "قس",
    "قش", "قص", "قط", "قع", "قف", "قل", "قم", "قن", "قه", "قو",
    "قی", "کا", "کت", "کد", "کر", "کز", "کس", "کش", "کف", "کل",
    "کم", "کن", "که", "کو", "کی", "گا", "گد", "گر", "گز", "گس",
    "گش", "گف", "گل", "گم", "گن", "گو", "گی", "لا", "لب", "لت",
    "لح", "لد", "لذ", "لر", "لز", "لس", "لش", "لع", "لغ", "لف",
    "لق", "لل", "لم", "لن", "له", "لو", "لی", "ما", "مت", "مج",
    "مح", "مد", "مر", "مز", "مس", "مش", "مص", "مض", "مع", "مغ",
    "مف", "مق", "مل", "مم", "من", "مه", "مو", "می", "نا", "نت",
    "نج", "نح", "ند", "نر", "نز", "نس", "نش", "نص", "نض", "نط",
    "نظ", "نع", "نف", "نق", "نل", "نم", "نن", "نه", "نو", "نی",
    "ها", "هب", "هد", "هر", "هز", "هس", "هش", "هل", "هم", "هن",
    "هو", "هی", "وا", "وت", "وج", "وح", "ود", "ور", "وز", "وس",
    "وش", "وص", "وض", "وط", "وظ", "وع", "وف", "وق", "ول", "وم",
    "ون", "وه", "وی", "یا", "یت", "ید", "یر", "یز", "یس", "یش",
    "یع", "یف", "یل", "یم", "ین", "یه", "یو",
}

# Arabic/Persian Unicode block
_PERSIAN_UNICODE_RANGE = range(0x0600, 0x06FF + 1)

# ---------------------------------------------------------------------------
# Persian legal lexicon — used by _compute_lexicon_validity() as the 5th
# quality signal.  Combines general Persian high-frequency words + legal
# domain terms + common verbs/prepositions.
#
# This is the MOST reliable signal for CMap corruption: garbled glyph
# indices produce tokens that simply don't exist in any Persian dictionary.
# ---------------------------------------------------------------------------
_PERSIAN_LEGAL_LEXICON: set = {
    # --- General Persian function words ---
    "از", "به", "در", "با", "برای", "و", "که", "این", "آن", "را",
    "تا", "یا", "اما", "اگر", "البته", "باید", "شاید", "ممکن",
    "بعد", "قبل", "زیر", "روی", "بین", "درباره", "مثل", "مانند",
    "چون", "زیرا", "بنابراین", "پس", "خواهد", "می", "است", "شد",
    "شود", "شده", "دارد", "داشت", "کرد", "کند", "گفت", "دهد",
    "بود", "باشند", "باشد", "نیز", "هم", "حدود", "سایر", "غیر",
    "هر", "تمام", "کل", "برخی", "بعضی", "چند", "چه", "چگونه",
    "کجا", "کی", "چرا", "هیچ", "نه", "بله", "آری", "خیر",
    "بر", "بدون", "جز", "جزء", "جزئی", "علت", "بابت", "جهت",
    "نسبت", "مربوط", "مرتبط", "طی", "ضمن", "هنگام", "موقع",
    "زمان", "مدت", "طرف", "سمت", "کنار", "داخل", "خارج", "بالا",
    "پایین", "اول", "آخر", "ابتدای", "انتها", "وسط", "میان",
    "قبل", "بعد", "فوق", "تحت", "پیش", "بیش", "کم", "زیاد",
    "خیلی", "بسیار", "اندک", "تقریبا", "حداکثر", "حداقل",
    "معادل", "مساوی", "مختلف", "متعدد", "عدیده",
    "همین", "همان", "چنین", "چنان", "مانند", "مثل",
    "تواند", "توانند", "می‌تواند", "می‌توانند",
    "نمی‌تواند", "نمی‌توانند", "بایستی", "می‌بایست",
    "هستند", "هستم", "هستی", "هستیم", "هستید",
    # --- Legal domain terms ---
    "دادگاه", "شعبه", "خواهان", "خوانده", "دادنامه", "پرونده",
    "کلاسه", "رأی", "رای", "حکم", "قانون", "ماده", "تبصره",
    "مصوب", "الزام", "محکوم", "مستند", "مستندات", "دلایل",
    "ادعا", "دعوی", "دعوا", "درخواست", "اعتراض", "تجدیدنظر",
    "فرجام", "وکالت", "وکیل", "مدعی", "منع", "قبول", "رد",
    "ابطال", "تنفیذ", "استرداد", "تامین", "خسارت", "هزینه",
    "دادرسی", "کارشناسی", "کارشناس", "شرح", "گردش", "کار",
    "مندرج", "ذیل", "صدر", "مبنی", "مبنی‌بر", "نظریه",
    "دادخواست", "شکایت", "متهم", "شاکی", "مشتکی‌عنه",
    "محکوم‌علیه", "محکوم‌له", "منتقل‌علیه", "منتقل‌له",
    "اجرت", "مثل", "وجه", "بهای", "ارزش", "مقدار", "مبلغ",
    "ریال", "تومان", "میلیون", "میلیارد", "هزار", "صد",
    "قرارداد", "توافق", "پیمان", "عهد", "ضمانت", "تضمین",
    "اجاره", "فروش", "خرید", "بیع", "معامله", "صلح", "هبه",
    "وقف", "وصیت", "ارث", "سهم", "حصه", "مال", "دارایی",
    "منقول", "غیرمنقول", "منافع", "عین", "دین", "طلب",
    "بدهی", "مطالبه", "وصول", "پرداخت", "تادیه", "ایفا",
    "تعهد", "التزام", "ضمان", "مسئولیت", "مسئول", "مسوولیت",
    "جبران", "غرامت", "جریمه", "مجازات", "کیفر", "حبس",
    "زندان", "جزای", "نقدی", "شلاق", "اعدام", "قصاص",
    "دیه", "ارش", "حکومت", "دولت", "جمهوری", "اسلامی",
    "ایران", "تهران", "مرکز", "استان", "شهرستان", "بخش",
    "اداره", "سازمان", "نهاد", "موسسه", "شرکت", "بنیاد",
    # --- Common Persian verbs (past and present stems) ---
    "است", "شد", "شود", "شده", "باشد", "بود", "باشند",
    "دارد", "داشت", "دارند", "داشتند",
    "کرد", "کند", "کنند", "کردند", "کنم", "کنی", "کند",
    "گفت", "گوید", "گویند", "گفتند",
    "داد", "دهد", "دهند", "دادند", "دهم", "دهی",
    "رفت", "رود", "روند", "رفتند", "روم", "روی",
    "آمد", "آید", "آیند", "آمدند", "آیم", "آیی",
    "نوشت", "نویسد", "نویسند", "نوشتند",
    "خواند", "خواند", "خوانند", "خواندند",
    "خواست", "خواهد", "خواهند", "خواستند",
    "دانست", "داند", "دانند", "دانستند",
    "توانست", "تواند", "توانند", "توانستند",
    "بست", "بندد", "بندند", "بستند",
    "گرفته", "گرفت", "گیرد", "گیرند", "گرفتند",
    "گذاشت", "گذارد", "گذارند", "گذاشتند",
    "آورد", "آورد", "آورند", "آوردند",
    "انداخت", "اندازد", "اندازند", "انداختند",
    "افزود", "افزاید", "افزایند", "افزودند",
    "کاست", "کاهد", "کاهند", "کاستند",
    # --- Common Persian nouns ---
    "انسان", "مردم", "شخص", "فرد", "نفر", "تن",
    "نام", "نشان", "عنوان", "اسم", "لقب", "کنیه",
    "زمین", "زمان", "مکان", "جا", "محل", "موضع",
    "روز", "ماه", "سال", "هفته", "دقیقه", "ساعت",
    "امروز", "دیروز", "فردا", "امسال", "پارسال",
    "کتاب", "نوشته", "متن", "سند", "مدرک", "برگه",
    "صفحه", "خط", "سطر", "کلمه", "واژه", "حرف",
    "عدد", "رقم", "شماره", "شماره", "نمره", "کد",
    "قسمت", "بخش", "فصل", "باب", "جزء",
    "نوع", "گونه", "قسم", "صنف", "دسته", "رده",
    "علت", "سبب", "دلیل", "جهت", "منظور", "هدف",
    "قدرت", "اختیار", "اجازه", "اذن", "مجوز",
    "حق", "تکلیف", "وظیفه", "مسئولیت", "بار",
    "نفع", "ضرر", "زیان", "خسارت", "صدمه",
    "امنیت", "آرامش", "نظم", "عدالت", "انصاف",
    "اثبات", "نفی", "اثر", "نتیجه", "حاصل",
    "شرط", "قید", "محدودیت", "استثنا",
    "اصل", "قاعده", "ضابطه", "معیار", "ملاک",
    "نماینده", "وکیل", "کارمند", "مستخدم", "کارگر",
    "رئیس", "رییس", "مدیر", "مسئول", "مسوول", "سرپرست",
    "عضو", "اعضا", "هیئت", "هیات", "مجمع", "شورا",
    "گواهی", "شهادت", "گواه", "شاهد", "مطلع",
    "سوگند", "قسامه", "یمین",
    "اظهارنامه", "اظهار", "اظهارات",
    "تصمیم", "قطعیت", "قطعی",
    "تخلف", "انجام", "صدور", "ابلاغ", "اجرا",
    "مهلت", "فرصت", "تاخیر", "تعویق", "تمدید",
    "فسخ", "انحلال", "بطلان", "لغو",
    "تفسیر", "تشریح", "تبیین", "توضیح",
    "استعلام", "استعلام", "پاسخ", "جواب",
}


def _compute_stopword_ratio(text: str) -> float:
    """Compute the ratio of Persian stopwords in the text.

    In valid Persian text, stopwords like ``از``, ``به``, ``در``, ``و``, ``که``
    appear frequently. In RTL-reversed or garbled text, these stopwords disappear
    or become unrecognizable.

    Args:
        text: The extracted text to evaluate.

    Returns:
        A float (0.0–1.0) representing the proportion of tokens that are
        known Persian stopwords. Returns 0.0 if no tokens are found.
    """
    words = text.split()
    if not words:
        return 0.0

    stopword_count = sum(1 for w in words if w in _ALL_PERSIAN_STOPWORDS)
    return stopword_count / len(words)


def _compute_bigram_plausibility(text: str) -> float:
    """Compute a bigram plausibility score for Persian text.

    Uses a pre-computed set of valid Persian bigrams. The score is the
    proportion of adjacent Persian character pairs that appear in the
    valid bigram set. Garbled text tends to have unusual bigram
    distributions (many invalid bigrams).

    Args:
        text: The extracted text to evaluate.

    Returns:
        A float (0.0–1.0) representing the proportion of valid Persian
        bigrams. Returns 1.0 if fewer than 2 Persian characters are found.
    """
    if not text:
        return 1.0

    # Collect all adjacent Persian character pairs
    persian_chars_only = "".join(
        ch for ch in text if ord(ch) in _PERSIAN_UNICODE_RANGE
    )

    if len(persian_chars_only) < 2:
        return 1.0

    valid_count = 0
    total_bigrams = 0

    for i in range(len(persian_chars_only) - 1):
        bigram = persian_chars_only[i : i + 2]
        total_bigrams += 1
        if bigram in _VALID_PERSIAN_BIGRAMS:
            valid_count += 1

    if total_bigrams == 0:
        return 1.0

    return valid_count / total_bigrams


def _compute_lexicon_validity(text: str) -> float:
    """Compute the fraction of extracted Persian tokens that are valid words.

    This is the **most reliable signal** for CMap corruption. When PyMuPDF
    mis-extracts glyphs due to a broken /ToUnicode CMap, the resulting tokens
    are random byte sequences that almost never match real Persian words.
    By contrast, valid Persian text (even with some noise) has a high
    proportion of dictionary-matching tokens.

    Uses :data:`_PERSIAN_LEGAL_LEXICON` — a curated set of ~500 high-frequency
    Persian words and legal domain terms.

    Args:
        text: The extracted text to evaluate.

    Returns:
        A float (0.0–1.0) representing the proportion of Persian tokens
        that appear in the lexicon. Returns 0.0 if no Persian tokens found.
    """
    tokens = text.split()
    if not tokens:
        return 0.0

    # Only consider tokens that contain at least one Persian character
    persian_tokens: list[str] = []
    for t in tokens:
        if any(ord(c) in _PERSIAN_UNICODE_RANGE for c in t):
            persian_tokens.append(t)

    if not persian_tokens:
        return 0.0

    # Also strip common punctuation from each token before matching
    import string  # noqa: PLC0415
    _punctuation = string.punctuation + "،؛؟«»""''()[]{}"

    valid_count = 0
    for token in persian_tokens:
        clean = token.strip(_punctuation)
        if clean in _PERSIAN_LEGAL_LEXICON:
            valid_count += 1

    return valid_count / len(persian_tokens)


def _compute_rtl_consistency(text: str) -> float:
    """Compute an RTL consistency score for Persian text.

    In valid Persian text, Persian characters appear in contiguous runs
    (words). RTL-reversed text often has Persian characters interspersed
    with non-Persian characters in unnatural patterns.

    This score measures the proportion of Persian characters that are
    adjacent to at least one other Persian character (i.e., part of a
    multi-character Persian word). This is similar to the inverse of the
    old ``_compute_garbled_ratio``.

    Args:
        text: The extracted text to evaluate.

    Returns:
        A float (0.0–1.0) where 1.0 means all Persian characters are
        part of multi-character runs (highly consistent), and 0.0 means
        all Persian characters are isolated. Returns 1.0 if no Persian
        characters are found.
    """
    if not text or not text.strip():
        return 1.0

    total_persian = 0
    connected_count = 0

    for i, ch in enumerate(text):
        if ord(ch) in _PERSIAN_UNICODE_RANGE:
            total_persian += 1
            prev_char = text[i - 1] if i > 0 else " "
            next_char = text[i + 1] if i + 1 < len(text) else " "

            prev_is_persian = ord(prev_char) in _PERSIAN_UNICODE_RANGE
            next_is_persian = ord(next_char) in _PERSIAN_UNICODE_RANGE

            # A character is "connected" if at least one neighbor is Persian
            if prev_is_persian or next_is_persian:
                connected_count += 1

    if total_persian == 0:
        return 1.0

    return connected_count / total_persian


def _compute_character_entropy(text: str) -> float:
    """Compute the Shannon entropy of Persian characters in the text.

    Garbled text often has higher entropy (more random character distribution)
    compared to natural Persian text which follows predictable patterns.

    Args:
        text: The extracted text to evaluate.

    Returns:
        A float representing the entropy (0.0+). Natural Persian text
        typically has entropy around 2.0–3.5. Garbled text can exceed 4.0.
        Returns 0.0 if no Persian characters are found.
    """
    if not text:
        return 0.0

    # Count frequency of each Persian character
    freq: dict[str, int] = {}
    total = 0
    for ch in text:
        if ord(ch) in _PERSIAN_UNICODE_RANGE:
            freq[ch] = freq.get(ch, 0) + 1
            total += 1

    if total == 0:
        return 0.0

    # Compute Shannon entropy: -sum(p * log2(p))
    import math
    entropy = 0.0
    for count in freq.values():
        p = count / total
        if p > 0:
            entropy -= p * math.log2(p)

    return entropy


# ---------------------------------------------------------------------------
# Bidi Parenthesis Fix — safe bracket balancing (NOT get_display())
# ---------------------------------------------------------------------------


def _fix_bidi_brackets(text: str) -> str:
    """Fix misplaced brackets in RTL text without changing logical order.

    Only performs LOCAL repairs:
    1. Closing bracket before Persian text → move after
    2. Opening bracket after Persian text → move before
    3. Does NOT attempt full bidi reordering (safe for storage)

    The order of operations is:
    a) Fix bracket positions (Patterns 1 and 2) — move brackets relative
       to adjacent Persian text segments.
    b) Balance bracket counts (Pattern 3) — remove truly unmatched
       brackets that Patterns 1 and 2 could not fix (difference >= 3).

    Args:
        text: The extracted text to repair.

    Returns:
        Text with brackets moved to correct positions relative to
        adjacent Persian text segments.
    """
    import re  # noqa: PLC0415

    _PERSIAN = '\\u0600-\\u06FF\\uFB8A\\uFE8D\\uFEE3\\uFEFB\\uFEFC'

    # ------------------------------------------------------------------
    # Step 1: Fix bracket positions (Patterns 1 and 2)
    # ------------------------------------------------------------------

    # Pattern 1: ) NOT preceded by Persian text, followed by Persian → text)
    # Uses negative lookbehind to avoid matching correctly-placed brackets
    # (e.g., سلام) where ) correctly follows Persian text in RTL context).
    text = re.sub(
        rf'(?<![{_PERSIAN}])\s*\)\s*([{_PERSIAN}]+)',
        r'\1)',
        text,
    )

    # Pattern 2: Persian text followed by ( NOT followed by Persian → (text)
    # Uses negative lookahead to avoid matching correctly-placed brackets
    # (e.g., (سلام where ( correctly precedes Persian text in RTL context).
    text = re.sub(
        rf'([{_PERSIAN}]+)\s*\(\s*(?![{_PERSIAN}])',
        r'(\1',
        text,
    )

    # ------------------------------------------------------------------
    # Step 2: Balance bracket counts (Pattern 3)
    # ------------------------------------------------------------------
    # Only removes brackets when the imbalance is >= 3. A difference of
    # 1 or 2 is assumed to be the result of Patterns 1 and 2 having moved
    # brackets to correct positions (e.g., )سلام → سلام) creates a single
    # trailing ), or ))سلام → سلام)) creates two trailing )).
    # When difference >= 3, there are truly extra brackets that position
    # fixing could not resolve.
    #
    # If ) count > ( count by 3+, remove trailing ) from end of line.
    # If ( count > ) count by 3+, remove leading ( from start of line.
    lines = text.split('\n')
    balanced: list[str] = []
    for line in lines:
        open_count = line.count('(')
        close_count = line.count(')')
        diff = abs(close_count - open_count)
        if diff >= 3:
            if close_count > open_count:
                # Remove extra closing brackets from the END (trailing)
                for _ in range(close_count - open_count):
                    idx = line.rfind(')')
                    if idx != -1:
                        line = line[:idx] + line[idx + 1:]
            elif open_count > close_count:
                # Remove extra opening brackets from the START (leading)
                for _ in range(open_count - close_count):
                    idx = line.find('(')
                    if idx != -1:
                        line = line[:idx] + line[idx + 1:]
        balanced.append(line)

    return '\n'.join(balanced)


def _compute_persian_quality_score(text: str) -> float:
    """Compute a quality score (0.0 = garbage, 1.0 = perfect) for Persian text.

    Combines **five** signals for robust garbled-text detection:

    1. **Stopword ratio** (weight 0.30) — Most reliable for RTL-reversed text.
       Persian stopwords like ``از``, ``به``, ``در`` disappear when reversed.
    2. **Lexicon validity** (weight 0.25) — Most reliable for CMap corruption.
       Garbled glyph indices produce tokens that don't exist in the Persian
       legal lexicon. (NEW in v2 refactoring)
    3. **Bigram plausibility** (weight 0.15) — Statistical bigram frequency.
       Helps detect random character substitution.
    4. **RTL consistency** (weight 0.20) — Detects shattered text where Persian
       chars are isolated by spaces.
    5. **Character entropy** (weight 0.10) — Garbled text often has higher
       entropy (more random character distribution).

    Args:
        text: The extracted text to evaluate.

    Returns:
        A float (0.0–1.0) representing the quality score.
        0.0 = completely garbled, 1.0 = perfect Persian text.
    """
    if not text or not text.strip():
        return 0.0

    signals = []

    # Signal 1: Stopword ratio (0.0–1.0)
    stopword_ratio = _compute_stopword_ratio(text)
    signals.append(stopword_ratio)

    # Signal 2: Lexicon validity (0.0–1.0)
    # NEW — strongest signal for CMap corruption
    lexicon_score = _compute_lexicon_validity(text)
    signals.append(lexicon_score)

    # Signal 3: Bigram plausibility (0.0–1.0)
    bigram_score = _compute_bigram_plausibility(text)
    signals.append(bigram_score)

    # Signal 4: RTL consistency (0.0–1.0)
    rtl_score = _compute_rtl_consistency(text)
    signals.append(rtl_score)

    # Signal 5: Character entropy (0.0–1.0, inverted)
    entropy = _compute_character_entropy(text)
    entropy_score = 1.0 - min(entropy / 5.0, 1.0)
    signals.append(entropy_score)

    # Weighted combination (updated for 5 signals)
    weights = [0.30, 0.25, 0.15, 0.20, 0.10]
    return sum(s * w for s, w in zip(signals, weights))


def _compute_garbled_ratio(text: str) -> float:
    """Compute the garbled ratio for Persian text (legacy heuristic).

    Uses a heuristic: counts the proportion of Persian/Arabic characters that
    appear isolated (surrounded by non-Persian characters). In properly rendered
    Persian text, most characters should be adjacent to other Persian characters.

    The Arabic/Persian Unicode block is U+0600–U+06FF.

    .. deprecated::
        Use :func:`_compute_persian_quality_score` instead, which combines
        multiple signals for more reliable detection.

    Args:
        text: The extracted text to evaluate.

    Returns:
        A float ratio (0.0–1.0) representing the proportion of isolated
        Persian characters. Returns 0.0 if no Persian characters are found.
    """
    if not text or not text.strip():
        return 0.0

    isolated_count = 0
    total_persian = 0

    for i, ch in enumerate(text):
        if ord(ch) in _PERSIAN_UNICODE_RANGE:
            total_persian += 1
            # Check if surrounded by non-Persian characters
            prev_char = text[i - 1] if i > 0 else " "
            next_char = text[i + 1] if i + 1 < len(text) else " "

            prev_is_persian = ord(prev_char) in _PERSIAN_UNICODE_RANGE
            next_is_persian = ord(next_char) in _PERSIAN_UNICODE_RANGE

            # A character is "isolated" if neither neighbor is Persian
            if not prev_is_persian and not next_is_persian:
                isolated_count += 1

    if total_persian == 0:
        return 0.0

    return isolated_count / total_persian


def _is_persian_text_garbled(
    text: str,
    threshold: float | None = None,
    *,
    use_quality_score: bool = True,
) -> bool:
    """Check if extracted Persian text appears garbled (RTL reversal).

    Uses the multi-signal :func:`_compute_persian_quality_score` by default,
    which combines stopword ratio, bigram plausibility, RTL consistency, and
    character entropy for more reliable detection.

    Falls back to the legacy :func:`_compute_garbled_ratio` if
    ``use_quality_score=False``.

    For documents detected as Persian legal text, uses the stricter
    ``EXTRACTION_GARBLED_THRESHOLD_PERSIAN_LEGAL`` threshold (default 0.15).

    Args:
        text: The extracted text to evaluate.
        threshold: Quality score threshold (0.0–1.0). If the quality score
            falls below this threshold, the text is considered garbled.
            Defaults to ``settings.EXTRACTION_GARBLED_THRESHOLD`` or 0.3.
            When ``use_quality_score=True``, a lower threshold means *stricter*
            (quality < threshold → garbled), so 0.4 means "quality below 0.4
            is garbled".
        use_quality_score: If ``True`` (default), uses the multi-signal
            quality score. If ``False``, uses the legacy garbled ratio.

    Returns:
        ``True`` if the text appears garbled, ``False`` otherwise.
    """
    if not text or not text.strip():
        return False

    if threshold is None:
        threshold = getattr(settings, "EXTRACTION_GARBLED_THRESHOLD", 0.3)

    if use_quality_score:
        quality = _compute_persian_quality_score(text)
        logger.debug(
            "Persian quality score: %.3f, threshold=%.2f",
            quality,
            threshold,
        )
        # Quality score < threshold → garbled (lower quality = more garbled)
        return quality < threshold
    else:
        ratio = _compute_garbled_ratio(text)
        logger.debug(
            "Persian garbled check (legacy): ratio=%.2f, threshold=%.2f",
            ratio,
            threshold,
        )
        return ratio > threshold


def _has_shattered_persian_words(text: str, threshold: float = 0.4) -> bool:
    """Detect if Persian text has shattered words (spaces between letters).

    In properly extracted Persian text, most space-delimited tokens contain
    multiple Persian characters (e.g., ``قانون``, ``مدنی``). When PyMuPDF
    mis-extracts RTL text, it inserts spaces between characters, turning
    ``قانون`` into ``ق ا ن و ن`` — each character becomes its own "word".

    This heuristic counts how many Persian "words" (space-delimited tokens)
    consist of a single Persian character. In normal Persian text, single-
    character words are rare (e.g., ``و`` meaning "and", ``به`` is two chars).
    In shattered text, almost every character becomes its own "word".

    Args:
        text: Extracted text to evaluate.
        threshold: If the ratio of single-Persian-char tokens to total
            Persian tokens exceeds this value, the text is considered
            shattered. Defaults to 0.4.

    Returns:
        ``True`` if text appears to have shattered Persian words.
    """
    tokens = text.split()
    if not tokens:
        return False

    single_char_count = 0
    persian_token_count = 0

    for token in tokens:
        # Count Persian chars in this token
        persian_chars = [c for c in token if ord(c) in _PERSIAN_UNICODE_RANGE]
        if not persian_chars:
            continue
        persian_token_count += 1
        # If the token is exactly one Persian character (possibly with
        # surrounding non-Persian), it's suspicious
        if len(persian_chars) == 1:
            single_char_count += 1

    if persian_token_count == 0:
        return False

    ratio = single_char_count / persian_token_count
    logger.debug(
        "Shattered Persian word check: %d/%d single-char tokens "
        "(ratio=%.2f, threshold=%.2f)",
        single_char_count,
        persian_token_count,
        ratio,
        threshold,
    )
    return ratio > threshold


# ---------------------------------------------------------------------------
# Extraction strategy helpers
# ---------------------------------------------------------------------------


def _extract_with_pymupdf_rtl(pdf_document: fitz.Document) -> str:
    """Extract text using PyMuPDF with RTL-aware flags.

    Uses ``TEXT_PRESERVE_LIGATURES`` and ``TEXT_PRESERVE_WHITESPACE`` flags
    to improve Persian/Arabic text extraction quality compared to bare
    ``page.get_text()``.

    Args:
        pdf_document: An open PyMuPDF document.

    Returns:
        Extracted text with ``[PAGE N]`` markers.
    """
    page_texts: list[str] = []
    for page_num in range(pdf_document.page_count):
        page = pdf_document.load_page(page_num)
        # RTL-aware flags for better Persian extraction.
        # TEXT_PRESERVE_LIGATURES: keeps Arabic/Persian ligatures intact.
        # TEXT_PRESERVE_WHITESPACE: preserves original whitespace layout.
        # TEXT_PRESERVE_IMAGES: includes image alt-text if present.
        # TEXT_DEHYPHENATE: re-joins hyphenated words broken across lines.
        text = page.get_text(
            "text",
            flags=(
                fitz.TEXT_PRESERVE_LIGATURES
                | fitz.TEXT_PRESERVE_WHITESPACE
                | fitz.TEXT_PRESERVE_IMAGES
                | fitz.TEXT_DEHYPHENATE
            ),
        )
        page_texts.append(f"[PAGE {page_num + 1}]\n{text}")
    return "\n".join(page_texts)


# ---------------------------------------------------------------------------
# Subtask 4a — Extract text from PDF (page-level, VLM fallback)
# ---------------------------------------------------------------------------


@shared_task(
    bind=True,
    autoretry_for=(IntegrityError, OperationalError, ConnectionError, TimeoutError),
    max_retries=3,
    retry_backoff=True,
    retry_backoff_max=60,
    retry_jitter=True,
)
def extract_text_from_pdf(self, document_id: str) -> str:
    """Open a PDF, extract text **per-page** with PyMuPDF + VLM fallback.

    **Page-level extraction pipeline:**

    1. **Primary: PyMuPDF with RTL flags** — Each page is extracted
       individually using ``TEXT_PRESERVE_LIGATURES``,
       ``TEXT_PRESERVE_WHITESPACE``, and ``TEXT_DEHYPHENATE`` flags.
    2. **Quality check (5 signals)** — Each page's text is evaluated using
       a multi-signal Persian quality score (stopwords, lexicon validity,
       bigram plausibility, RTL consistency, character entropy).
    3. **VLM fallback** — If a page's quality score is below threshold,
       the page is rendered to a PNG image via PyMuPDF's
       :meth:`~fitz.Page.get_pixmap` and sent to Qwen3 VL via OpenRouter
       for vision-based text extraction. Only garbled pages are sent.

    This replaces the old multi-stage fallback chain (pdfplumber →
    Tesseract → EasyOCR) with a single, page-level, VLM-based path.

    After extraction, per-page normalization is applied, followed by
    table extraction (PyMuPDF), bidi bracket fixes, and metadata storage.

    Args:
        document_id: The UUID (as a string) of the :class:`Document` to process.

    Returns:
        The full extracted text with ``[PAGE N]`` markers inserted between pages.
        Returns an empty string for empty PDFs (0 pages).
    """
    log_milestone(logger, document_id, "Starting extraction")

    try:
        document = Document.objects.get(id=document_id)
    except Document.DoesNotExist:
        logger.error("extract_text_from_pdf: Document %s not found", document_id)
        return ""

    # Find the pending ProcessingTask created by process_document().
    processing_task = ProcessingTask.objects.filter(
        document=document,
        task_type="extract",
        status="pending",
    ).order_by("-created_at").first()

    if processing_task is None:
        processing_task = ProcessingTask.objects.create(
            document=document,
            task_type="extract",
            celery_task_id=self.request.id,
            status="running",
            started_at=timezone.now(),
        )
    else:
        processing_task.celery_task_id = self.request.id
        processing_task.status = "running"
        processing_task.started_at = timezone.now()
        processing_task.save(
            update_fields=["celery_task_id", "status", "started_at"]
        )

    # Mark the document as processing.
    document.processing_status = "processing"
    document.status = "processing"
    document.save(update_fields=["processing_status", "status"])

    try:
        # Resolve the PDF content using the storage backend.
        storage = get_storage_backend()
        logger.info(
            "extract_text_from_pdf: Opening file_path=%s for document %s",
            document.file_path,
            document_id,
        )
        pdf_content = storage.open(document.file_path)

        # Check PDF magic bytes before attempting to open.
        header = pdf_content.read(4)
        pdf_content.seek(0)
        if header != b"%PDF":
            fail_processing_task(
                processing_task, document, "File is not a valid PDF", logger,
            )
            return ""

        pdf_document = fitz.open(stream=pdf_content, filetype="pdf")
    except fitz.FileDataError as e:
        error_msg = classify_pdf_error(e, document.file_path)
        fail_processing_task(processing_task, document, error_msg, logger)
        return ""
    except Exception as e:
        error_msg = classify_pdf_error(e, document.file_path)
        logger.exception(
            "extract_text_from_pdf: Unhandled exception for document %s "
            "(file_path=%s, error_type=%s)",
            document_id,
            document.file_path,
            type(e).__name__,
        )
        fail_processing_task(processing_task, document, error_msg, logger)
        return ""

    try:
        num_pages = pdf_document.page_count
        if num_pages == 0:
            logger.info(
                "extract_text_from_pdf: Document %s has 0 pages — "
                "returning empty string",
                document_id,
            )
            document.extracted_text_length = 0
            document.save(update_fields=["extracted_text_length"])
            processing_task.status = "completed"
            processing_task.completed_at = timezone.now()
            processing_task.save(update_fields=["status", "completed_at"])
            return ""

        # ------------------------------------------------------------------
        # Read PDF bytes early for table extraction
        # ------------------------------------------------------------------
        pdf_bytes = (
            pdf_content.read()
            if hasattr(pdf_content, "read")
            else pdf_content
        )

        # ------------------------------------------------------------------
        # PAGE-LEVEL EXTRACTION LOOP (replaces old whole-document approach)
        # ------------------------------------------------------------------
        # Each page is extracted independently with PyMuPDF, checked for
        # quality, and only problematic pages are routed to the VLM.
        # This avoids both false positives (sending entire document to VLM
        # for just a few bad pages) and false negatives (missing garbled
        # pages because the average is OK).
        # ------------------------------------------------------------------
        vision_service: VisionExtractionService | None = None
        vision_enabled = getattr(settings, "VISION_EXTRACTION_ENABLED", True)
        page_results: list[str] = []
        garbled_page_indices: list[int] = []  # Collect garbled pages for batch VLM
        vl_page_count = 0
        unverified_pages: list[dict] = []

        # ------------------------------------------------------------------
        # PASS 1: Extract all pages with PyMuPDF, check quality, collect
        # garbled page indices for batch VLM processing.
        # ------------------------------------------------------------------
        for page_num in range(num_pages):
            page = pdf_document.load_page(page_num)

            # Stage 1: Extract with PyMuPDF RTL flags
            text = page.get_text(
                "text",
                flags=(
                    fitz.TEXT_PRESERVE_LIGATURES
                    | fitz.TEXT_PRESERVE_WHITESPACE
                    | fitz.TEXT_PRESERVE_IMAGES
                    | fitz.TEXT_DEHYPHENATE
                ),
            )

            text = text or ""

            # Stage 2: Page-level quality check (5 signals)
            is_garbled = _is_persian_text_garbled(
                text,
                threshold=getattr(settings, "EXTRACTION_GARBLED_THRESHOLD", 0.3),
            ) or _has_shattered_persian_words(text)

            # If PyMuPDF produced very little text, consider it garbled
            has_selectable_text = len(text.strip()) > 50
            if not has_selectable_text:
                is_garbled = True

            if is_garbled:
                garbled_page_indices.append(page_num)

            # Stage 3: Per-page Persian normalization (preliminary)
            if getattr(settings, "PERSIAN_NORMALIZATION_ENABLED", True):
                try:
                    normalizer = PersianNormalizer()
                    text = normalizer.normalize(text)
                except Exception as e:
                    logger.warning(
                        "extract_text_from_pdf: Persian normalization failed "
                        "for page %d of document %s: %s",
                        page_num + 1,
                        document_id,
                        e,
                    )

            # Store placeholder text (will be replaced if VLM succeeds)
            page_results.append(f"[PAGE {page_num + 1}]\n{text}")

            # ── Report PASS 1 progress (PyMuPDF extraction) ──────────────
            # Progress is calculated as a fraction of total pages.
            # After this pass, if garbled pages exist, progress will be
            # recalculated below to reflect the REAL total work
            # (non-garbled pages via PyMuPDF + garbled pages via VLM).
            try:
                page_progress = int((page_num + 1) / num_pages * 100)
                processing_task.progress = page_progress
                processing_task.save(update_fields=["progress"])
            except Exception:
                pass  # Non-critical — don't fail extraction if progress save fails

        # ------------------------------------------------------------------
        # PASS 2: Batch-process all garbled pages via VLM (single API call
        # per batch of 4 pages — much faster than sequential per-page calls).
        # ------------------------------------------------------------------
        non_garbled_count = num_pages - len(garbled_page_indices)

        if garbled_page_indices and vision_enabled:
            # Recalculate progress to reflect REAL total work:
            # non-garbled pages (PyMuPDF, already done) + garbled pages (VLM, pending).
            # This "drops" progress from 100% to the true % of completed work.
            try:
                real_progress = int(non_garbled_count / num_pages * 100)
                processing_task.progress = real_progress
                processing_task.save(update_fields=["progress"])
            except Exception:
                pass
            from concurrent.futures import ThreadPoolExecutor, as_completed

            try:
                if vision_service is None:
                    vision_service = VisionExtractionService()

                logger.info(
                    "extract_text_from_pdf: Parallel VLM extraction for %d "
                    "garbled pages of document %s (max_workers=4)",
                    len(garbled_page_indices),
                    document_id,
                )

                # Process garbled pages in parallel using ThreadPoolExecutor.
                # VLM API calls are I/O-bound (HTTP requests), so threading
                # provides near-linear speedup: 16 pages / 4 workers = 4 rounds.
                completed_vlm = 0
                total_garbled = len(garbled_page_indices)

                with ThreadPoolExecutor(max_workers=4) as executor:
                    futures = {
                        executor.submit(
                            vision_service.extract_page,
                            pdf_document,
                            page_idx,  # 0-based
                        ): page_idx
                        for page_idx in garbled_page_indices
                    }

                    for future in as_completed(futures):
                        page_idx = futures[future]
                        vl_result = future.result()
                        page_num_1based = page_idx + 1
                        completed_vlm += 1

                        # ── Report PASS 2 progress (VLM garbled pages) ────
                        # Progress = (non_garbled via PyMuPDF + completed via VLM) / total pages
                        try:
                            vlm_progress = int(
                                (non_garbled_count + completed_vlm) / num_pages * 100
                            )
                            processing_task.progress = vlm_progress
                            processing_task.save(update_fields=["progress"])
                        except Exception:
                            pass

                        if vl_result.text and len(vl_result.text.strip()) > 10:
                            vl_text = vl_result.text
                            # Apply Persian normalization to VLM output
                            if getattr(settings, "PERSIAN_NORMALIZATION_ENABLED", True):
                                try:
                                    normalizer = PersianNormalizer()
                                    vl_text = normalizer.normalize(vl_text)
                                except Exception:
                                    pass

                            page_results[page_idx] = (
                                f"[PAGE {page_num_1based}]\n{vl_text}"
                            )
                            vl_page_count += 1

                        if not vl_result.verified:
                            unverified_pages.append({
                                "page": page_num_1based,
                                "flags": vl_result.verification_flags,
                            })

            except Exception as e:
                logger.warning(
                    "extract_text_from_pdf: Parallel VLM extraction failed for "
                    "document %s: %s — keeping PyMuPDF output for garbled pages",
                    document_id,
                    e,
                )

        # Assemble all pages
        extracted_text = "\n".join(page_results)

        # Determine extraction method for metadata
        # NOTE: extraction_method is VARCHAR(20) in the Document model.
        # Keep values short to avoid database truncation errors.
        if vl_page_count > 0:
            if vl_page_count == num_pages:
                extraction_method = "vision_only"
            else:
                extraction_method = "pymupdf_mixed"
        else:
            extraction_method = "pymupdf"

        # Log VLM usage
        if vl_page_count > 0:
            logger.info(
                "extract_text_from_pdf: VLM used for %d/%d pages of "
                "document %s (%d unverified)",
                vl_page_count,
                num_pages,
                document_id,
                len(unverified_pages),
            )

        # ------------------------------------------------------------------
        # Table extraction — detect tables using PyMuPDF
        # ------------------------------------------------------------------
        table_extraction_enabled = getattr(
            settings, "TABLE_EXTRACTION_ENABLED", True
        )
        extracted_tables: list[dict] = []
        if table_extraction_enabled:
            try:
                from documents.utils.table_extractor import (  # noqa: PLC0415
                    TableExtractor,
                )

                extractor = TableExtractor()
                tables = extractor.extract_tables(pdf_bytes)
                for t in tables:
                    extracted_tables.append(
                        {
                            "page": t.page,
                            "bbox": list(t.bbox),
                            "markdown": t.markdown,
                            "semantic_text": t.semantic_text,
                        }
                    )
                if extracted_tables:
                    logger.info(
                        "extract_text_from_pdf: Extracted %d table(s) "
                        "for document %s",
                        len(extracted_tables),
                        document_id,
                    )
            except Exception as e:
                logger.warning(
                    "extract_text_from_pdf: Table extraction failed for "
                    "document %s: %s — continuing without tables",
                    document_id,
                    e,
                )

        # ------------------------------------------------------------------
        # Apply bidi bracket fix (safe local repairs)
        # ------------------------------------------------------------------
        if getattr(settings, "BIDI_BRACKET_FIX_ENABLED", True):
            try:
                extracted_text = _fix_bidi_brackets(extracted_text)
            except Exception as e:
                logger.warning(
                    "extract_text_from_pdf: Bidi bracket fix failed for "
                    "document %s: %s — continuing with unfixed text",
                    document_id,
                    e,
                )

        # ------------------------------------------------------------------
        # Compute quality scores and store metadata
        # ------------------------------------------------------------------
        quality_score = _compute_persian_quality_score(extracted_text)
        garbled_score = _compute_garbled_ratio(extracted_text)

        # Build vision verification metadata
        vision_verification: dict[str, Any] = {
            "vl_pages": vl_page_count,
            "total_pages": num_pages,
            "unverified_pages": unverified_pages,
        }

        # Update document metadata
        document.extracted_text = extracted_text
        document.extraction_method = extraction_method
        document.garbled_score = garbled_score
        document.extracted_text_length = len(extracted_text)
        document.total_pages = num_pages
        document.tables_data = extracted_tables
        document.save(
            update_fields=[
                "extracted_text",
                "extraction_method",
                "garbled_score",
                "extracted_text_length",
                "total_pages",
                "tables_data",
            ]
        )

        logger.info(
            "extract_text_from_pdf: Document %s quality_score=%.3f "
            "(garbled_ratio=%.3f, method=%s, chars=%d, pages=%d)",
            document_id,
            quality_score,
            garbled_score,
            extraction_method,
            len(extracted_text),
            num_pages,
        )

        # Mark the ProcessingTask as completed with final progress.
        processing_task.status = "completed"
        processing_task.progress = 100
        processing_task.completed_at = timezone.now()
        processing_task.save(update_fields=["status", "progress", "completed_at"])

        log_milestone(
            logger, document_id, "Extraction complete",
            pages=num_pages, chars=len(extracted_text),
        )

        return extracted_text

    finally:
        # Ensure pdf_document is always closed, even if an exception occurs
        pdf_document.close()


# ---------------------------------------------------------------------------
# Subtask 4b — Chunk extracted text
# ---------------------------------------------------------------------------


@shared_task(
    bind=True,
    autoretry_for=(IntegrityError, OperationalError, ConnectionError, TimeoutError),
    max_retries=3,
    retry_backoff=True,
    retry_backoff_max=60,
    retry_jitter=True,
    soft_time_limit=300,
    time_limit=600,
)
def chunk_document(self, extracted_text: str, document_id: str) -> None:
    """Split ``extracted_text`` into chunks and persist them to the database.

    Uses the :class:`~documents.services.anchor_chunking_service.AnchorChunkingService`
    which applies text anchor (لنگر متنی) segmentation for Persian legal documents,
    with token-based overlap splitting for long segments. Metadata is stored
    separately from chunk content to avoid embedding pollution.

    This task is designed to be the second link in a Celery chain, receiving
    ``extracted_text`` from :func:`extract_text_from_pdf`.

    Transient database/storage errors are automatically retried up to 3 times
    with exponential backoff.

    Args:
        extracted_text: The full extracted text (with page markers) returned by
            the extraction task.
        document_id: The UUID (as a string) of the :class:`Document`.
    """
    log_milestone(logger, document_id, "Starting chunking")

    try:
        document = Document.objects.get(id=document_id)
    except Document.DoesNotExist:
        logger.error("chunk_document: Document %s not found", document_id)
        return

    # If the document is already in a terminal failed state, skip entirely.
    if document.processing_status == "failed":
        logger.info(
            "chunk_document: Document %s is already failed — skipping chunking",
            document_id,
        )
        return

    # Create a new ProcessingTask for the chunk step.
    chunk_task = ProcessingTask.objects.create(
        document=document,
        task_type="chunk",
        celery_task_id=self.request.id,
        status="running",
        started_at=timezone.now(),
    )

    # Handle empty text — mark as failed.
    if not extracted_text or not extracted_text.strip():
        logger.warning(
            "chunk_document: Document %s has no extracted text — marking as failed",
            document_id,
        )
        fail_processing_task(
            chunk_task,
            document,
            "Text extraction produced no content. The PDF may be image-based, "
            "scanned, or contain unsupported characters.",
            logger,
        )
        return

    try:
        # Use PersianLegalChunker (semantic chunking) or fallback to
        # AnchorChunkingService based on settings.
        chunk_tokens = getattr(settings, "ANCHOR_CHUNK_TOKENS", 400)
        overlap_tokens = getattr(settings, "ANCHOR_OVERLAP_TOKENS", 50)

        if getattr(settings, "PERSIAN_LEGAL_CHUNKER_ENABLED", True):
            chunker = PersianLegalChunker(
                min_chunk_tokens=getattr(settings, "MIN_CHUNK_TOKENS", 150),
                max_chunk_tokens=chunk_tokens,
                overlap_sentences=getattr(settings, "OVERLAP_SENTENCES", 1),
            )
        else:
            chunker = AnchorChunkingService()

        chunk_results = chunker.chunk_text(
            extracted_text,
            chunk_tokens=chunk_tokens,
            overlap_tokens=overlap_tokens,
        )

        # Filter out non-text chunks (e.g., table of contents) before
        # persisting to the database. This prevents structural artifacts from
        # polluting the vector store.
        if getattr(settings, "NON_TEXT_CHUNK_FILTERING_ENABLED", True):
            pre_filter_count = len(chunk_results)
            non_text_filter = NonTextChunkFilter()
            chunk_results = non_text_filter.filter_chunks(chunk_results)
            filtered_count = pre_filter_count - len(chunk_results)
            if filtered_count > 0:
                logger.info(
                    "Non-text chunk filter removed %d chunk(s) "
                    "(kept %d) for document %s",
                    filtered_count,
                    len(chunk_results),
                    document_id,
                )

        # Build DocumentChunk instances with metadata.
        # The AnchorChunk stores metadata SEPARATELY from content (no
        # embedding pollution). Denormalized fields (law_name, legal_status,
        # approval_date, legal_type) are populated from chunk.metadata for
        # efficient SQL-level filtering.
        #
        # IMPORTANT: Normalize chunk content for FTS before saving. The DB
        # trigger ``trg_chunk_search_vector`` builds the ``search_vector``
        # using ``to_tsvector('simple', ...)``, which does NOT convert Persian
        # digits (۰۱۲۳۴۵۶۷۸۹) to English digits (0123456789). By normalizing
        # here, we ensure the stored content (and thus the ``search_vector``)
        # uses English digits, so FTS queries with English digits match correctly.
        #
        # AnchorChunk uses ``pages: List[int]`` — we map min(pages) to
        # page_start and max(pages) to page_end for backward compatibility
        # with the DocumentChunk model.
        #
        # Table metadata: Tables extracted during the extract step are stored
        # on ``document.tables_data``. For each chunk, we attach tables that
        # fall within the chunk's page range. Tables are stored as metadata
        # (not injected into content) to prevent embedding pollution.
        # The semantic_text representation is used for embedding, while the
        # markdown representation is available for LLM context.
        document_tables: list[dict] = document.tables_data or []

        def _get_tables_for_chunk(
            chunk_pages: list[int],
        ) -> list[dict]:
            """Get tables whose page overlaps with the chunk's page range."""
            if not document_tables or not chunk_pages:
                return []
            page_min = min(chunk_pages)
            page_max = max(chunk_pages)
            return [
                {
                    "page": t["page"],
                    "markdown": t["markdown"],
                    "semantic_text": t["semantic_text"],
                }
                for t in document_tables
                if page_min <= t["page"] <= page_max
            ]

        chunks_to_create = [
            DocumentChunk(
                document=document,
                chunk_index=i,
                page_start=min(chunk.pages) if chunk.pages else 1,
                page_end=max(chunk.pages) if chunk.pages else 1,
                content=PersianNormalizer.normalize_for_fts(chunk.content),
                token_count=chunk.token_count,
                metadata={
                    **chunk.metadata,
                    "tables": _get_tables_for_chunk(chunk.pages),
                },
                law_name=chunk.metadata.get("law_name"),
                legal_status=chunk.metadata.get("legal_status"),
                approval_date=chunk.metadata.get("approval_date"),
                legal_type=chunk.metadata.get("legal_type"),
            )
            for i, chunk in enumerate(chunk_results)
        ]

        try:
            with transaction.atomic():
                DocumentChunk.objects.bulk_create(chunks_to_create)
        except (IntegrityError, OperationalError) as e:
            fail_processing_task(
                chunk_task, document,
                "Database error during chunking",
                logger,
            )
            return

        # Update document metadata.
        document.total_chunks = len(chunks_to_create)
        document.save(update_fields=["total_chunks"])

        # Mark the chunk ProcessingTask as completed.
        chunk_task.status = "completed"
        chunk_task.completed_at = timezone.now()
        chunk_task.save(update_fields=["status", "completed_at"])

        log_milestone(
            logger, document_id, "Chunking complete",
            chunks=len(chunks_to_create),
        )

    except Exception:
        error_message = traceback.format_exc()
        fail_processing_task(chunk_task, document, error_message, logger)


# ---------------------------------------------------------------------------
# Subtask 4c — Orchestration (Celery chain)
# ---------------------------------------------------------------------------


@shared_task(bind=True)
def _handle_chain_error(
    self,
    request: Any,
    exc: Exception,
    traceback_obj: Any,
    document_id: str,
    task_type: str = "extract",
) -> None:
    """Error callback for the Celery chain.

    When the chain fails (e.g., worker crash, unhandled exception), this task
    is triggered via ``link_error`` to update the ``ProcessingTask`` status
    to ``"failed"`` so it doesn't remain stuck at ``"pending"`` forever.

    Celery's ``link_error`` passes ``(request, exc, traceback)`` as positional
    args **before** the signature args (``document_id``, ``task_type``).
    """
    log_milestone(
        logger, document_id,
        "Chain failed — marking %s task as failed" % task_type,
    )

    try:
        document = Document.objects.get(id=document_id)
    except Document.DoesNotExist:
        logger.error("_handle_chain_error: Document %s not found", document_id)
        return

    processing_task = ProcessingTask.objects.filter(
        document=document,
        task_type=task_type,
        status__in=("pending", "running"),
    ).order_by("-created_at").first()

    if processing_task:
        processing_task.status = "failed"
        processing_task.error_message = (
            processing_task.error_message
            or "Chain-level failure: the Celery pipeline encountered an unrecoverable error"
        )
        processing_task.completed_at = timezone.now()
        processing_task.save(update_fields=["status", "error_message", "completed_at"])

    if document.processing_status not in ("completed", "failed"):
        document.processing_status = "failed"
        document.status = "failed"
        document.processing_error = (
            document.processing_error
            or "Chain-level failure: the Celery pipeline encountered an unrecoverable error"
        )
        document.save(update_fields=["processing_status", "status", "processing_error"])
