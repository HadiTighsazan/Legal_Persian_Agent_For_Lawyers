# WIP Context — Task 2: Serializers for Conversations & Messages

## What Was Just Completed
- Refactored `ConversationListSerializer` and `ConversationDetailSerializer` based on DRF best-practice review:
  1. **N+1 Query Fix**: Changed `message_count` from `SerializerMethodField` (which triggers `.count()` per instance) to `IntegerField(read_only=True)`. The view is now responsible for annotating the queryset with `Count('messages', distinct=True)`.
  2. **ModelSerializer Base Class**: Changed both serializers from `serializers.Serializer` to `serializers.ModelSerializer` with proper `Meta` classes, reducing boilerplate and adhering to DRF standards.
  3. **Context User Validation**: Confirmed `ConversationCreateSerializer.validate_document_id()` already extracts the user securely via `self.context['request'].user` and checks `document.user != request.user`.
- Updated tests to annotate conversations with `Count('messages')` before passing to serializers, matching the expected view behavior.
- All 28 tests pass.

## Current State
- `src/backend/conversations/serializers.py` — Refactored with all 6 serializers using proper base classes
- `src/backend/conversations/tests/test_serializers.py` — Updated tests use `_get_annotated_conversation()` helper to simulate view-level annotation

## Next Step
- Proceed to implement views/URLs for the conversations endpoints.
