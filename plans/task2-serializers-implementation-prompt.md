# Task 2 — Serializers for Conversations & Messages

## Implementation Prompt for Code Mode

### Objective

Create a new file [`src/backend/conversations/serializers.py`](src/backend/conversations/serializers.py) with **6 serializers** and their corresponding **unit tests** in [`src/backend/conversations/tests/`](src/backend/conversations/tests/).

---

## Part 1: Serializer Implementation (`src/backend/conversations/serializers.py`)

Create the following serializers. Follow the existing patterns from [`src/backend/documents/serializers.py`](src/backend/documents/serializers.py) (help_text on every field, docstrings, type hints).

### 1. `MessageSerializer`

- **Model:** `Message` (from [`src/backend/conversations/models.py`](src/backend/conversations/models.py))
- **Fields:** `id` (UUIDField, read_only), `role` (CharField), `content` (CharField), `sources` (JSONField, read_only — serialized as JSONB array), `token_usage` (JSONField, read_only, allow_null=True), `created_at` (DateTimeField, read_only)
- **Note:** `sources` is a `JSONField(default=list)` on the model, so it's always a list. Use `read_only=True` since sources are set programmatically by the RAG pipeline, not by user input.

### 2. `ConversationListSerializer`

- **Model:** `Conversation`
- **Fields:** `id` (UUIDField, read_only), `document_id` (UUIDField, read_only, source='document.id'), `document_title` (CharField, read_only, source='document.title'), `title` (CharField), `message_count` (SerializerMethodField or IntegerField with annotation), `created_at` (DateTimeField, read_only), `updated_at` (DateTimeField, read_only)
- **`message_count`:** Use `SerializerMethodField` that returns `obj.messages.count()`. Alternatively, if the view annotates with `Count('messages')`, use `IntegerField(read_only=True)`. For now, use `SerializerMethodField` for simplicity.

### 3. `ConversationDetailSerializer`

- **Model:** `Conversation`
- **Fields:** All fields from `ConversationListSerializer` + `messages` (MessageSerializer, many=True, read_only)
- **Inherits from `ConversationListSerializer`** to avoid duplication.

### 4. `ConversationCreateSerializer`

- **Purpose:** Validate input for POST `/conversations`
- **Fields:** `document_id` (UUIDField, required), `title` (CharField, required=False, allow_blank=True, max_length=500)
- **`validate(document_id)` method:**
  1. Look up `Document.objects.get(id=value)` — if not found, raise `ValidationError("Document does not exist")`
  2. Check `document.user == request.user` — if not, raise `ValidationError("Document does not belong to you")`
  3. Check `document.processing_status == 'completed'` — if not, raise `ValidationError("Document processing is not complete")`
  4. Return the document instance (not the UUID)
- **Access request.user:** Use `self.context['request'].user` (standard DRF pattern)

### 5. `AskQuestionSerializer`

- **Purpose:** Validate input for POST `/conversations/{id}/messages`
- **Fields:** `content` (CharField, required=True, min_length=1, max_length=10000)

### 6. `DirectQuerySerializer`

- **Purpose:** Validate input for POST `/documents/{document_id}/query`
- **Fields:** `question` (CharField, required=True, min_length=1), `top_k` (IntegerField, required=False, default=5, min_value=1, max_value=20)

---

## Part 2: Unit Tests (`src/backend/conversations/tests/test_serializers.py`)

Create a new test file. Follow the exact patterns from [`src/backend/documents/tests/test_serializers.py`](src/backend/documents/tests/test_serializers.py) (setUp, subTest for help_text, type hints, docstrings).

### Test Classes

#### `MessageSerializerTests`
- `test_valid_data_passes` — Provide all fields, assert `is_valid()`
- `test_read_only_fields` — Verify `id`, `created_at`, `sources`, `token_usage` are read_only
- `test_serializes_output` — Pass an instance dict, verify output types (UUID→str, datetime→str)
- `test_help_text_on_all_fields`

#### `ConversationListSerializerTests`
- `test_valid_data_passes` — Provide all fields including `message_count`
- `test_serializes_output` — Verify UUID→str, datetime→str
- `test_document_title_from_source` — Verify `document_title` comes from source
- `test_help_text_on_all_fields`

#### `ConversationDetailSerializerTests`
- `test_valid_data_passes` — Include nested `messages` list
- `test_serializes_output` — Verify nested messages are serialized
- `test_empty_messages_list` — Empty messages list is valid
- `test_help_text_on_all_fields`

#### `ConversationCreateSerializerTests`
- **Requires DB access** — Use `django.test.TestCase`
- `setUp` — Create a `User`, a `Document` with `processing_status='completed'` owned by that user
- `test_valid_data_passes` — Valid document_id + title
- `test_valid_data_without_title` — Valid document_id, no title
- `test_non_existent_document` — Random UUID → `ValidationError`
- `test_wrong_owner_document` — Document owned by different user → `ValidationError`
- `test_unprocessed_document` — Document with `processing_status='pending'` → `ValidationError`
- `test_help_text_on_all_fields`

#### `AskQuestionSerializerTests`
- `test_valid_content_passes`
- `test_empty_content_fails` — Empty string fails (min_length=1)
- `test_content_too_long` — String > 10000 chars fails
- `test_missing_content_fails`
- `test_help_text_on_all_fields`

#### `DirectQuerySerializerTests`
- `test_valid_data_passes` — question + top_k
- `test_default_top_k` — Omitting top_k gives default 5
- `test_top_k_min_value` — top_k=0 fails
- `test_top_k_max_value` — top_k=21 fails
- `test_empty_question_fails`
- `test_help_text_on_all_fields`

---

## Implementation Notes

1. **File structure:**
   - [`src/backend/conversations/serializers.py`](src/backend/conversations/serializers.py) — All 6 serializers
   - [`src/backend/conversations/tests/test_serializers.py`](src/backend/conversations/tests/test_serializers.py) — All test classes
   - Create `src/backend/conversations/tests/__init__.py` if it doesn't exist

2. **Imports needed:**
   ```python
   from rest_framework import serializers
   from django.db import models  # for annotating message_count if needed
   from conversations.models import Conversation, Message
   from documents.models import Document
   ```

3. **`ConversationCreateSerializer` context:** The view must pass `{'request': request}` in the serializer context. The serializer accesses it via `self.context['request'].user`.

4. **`ConversationDetailSerializer` inheritance:**
   ```python
   class ConversationDetailSerializer(ConversationListSerializer):
       messages = MessageSerializer(many=True, read_only=True)
       
       class Meta(ConversationListSerializer.Meta):
           fields = ConversationListSerializer.Meta.fields + ['messages']
   ```

5. **Test for `ConversationCreateSerializer`:** Since it needs DB access, use `TestCase` (not `SerializerTestCase`). Create actual User and Document instances.

6. **Run tests with:** `docker-compose exec backend pytest src/backend/conversations/tests/test_serializers.py -v`

---

## Architecture Diagram

```mermaid
flowchart TD
    subgraph Serializers
        MS[MessageSerializer]
        CLS[ConversationListSerializer]
        CDS[ConversationDetailSerializer]
        CCS[ConversationCreateSerializer]
        AQS[AskQuestionSerializer]
        DQS[DirectQuerySerializer]
    end

    subgraph Models
        Conv[Conversation]
        Msg[Message]
        Doc[Document]
    end

    MS --> Msg
    CLS --> Conv
    CDS --> CLS
    CDS --> MS
    CCS --> Doc
    AQS -.->|validates content| Msg
    DQS -.->|validates question| Doc

    subgraph Endpoints
        E1[POST /conversations]
        E2[GET /conversations]
        E3[GET /conversations/{id}]
        E4[POST /conversations/{id}/messages]
        E5[POST /documents/{id}/query]
    end

    CCS --> E1
    CLS --> E2
    CDS --> E3
    AQS --> E4
    DQS --> E5
```

---

## Acceptance Criteria Checklist

- [ ] `MessageSerializer` — All fields correct, read_only fields verified
- [ ] `ConversationListSerializer` — `document_title` via source, `message_count` via method
- [ ] `ConversationDetailSerializer` — Inherits from list, includes nested messages
- [ ] `ConversationCreateSerializer` — Validates: document exists, correct owner, processing completed
- [ ] `AskQuestionSerializer` — content min_length=1, max_length=10000
- [ ] `DirectQuerySerializer` — question min_length=1, top_k default=5, range 1-20
- [ ] All serializers have `help_text` on every field
- [ ] All test classes cover valid + invalid inputs
- [ ] All tests pass with `docker-compose exec backend pytest`
