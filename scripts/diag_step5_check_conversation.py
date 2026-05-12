"""
Diagnostic Step 5: Check the conversation's stored hub_metadata.

This script:
1. Fetches the specific conversation f8c57557-9773-46ff-a688-ab2f0100908f
2. Gets the assistant message and its hub_metadata
3. Shows what was actually retrieved per hub
4. Shows the sources that were returned
"""
import os
import sys
import json

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django
django.setup()

from conversations.models import Conversation, Message

print("=" * 70)
print("STEP 5: CHECK CONVERSATION HUB METADATA")
print("=" * 70)

CONVERSATION_ID = "f8c57557-9773-46ff-a688-ab2f0100908f"

# ---------------------------------------------------------------------------
# 5a. Fetch the conversation
# ---------------------------------------------------------------------------
print("\n" + "-" * 70)
print(f"5a: FETCHING CONVERSATION {CONVERSATION_ID}")
print("-" * 70)

try:
    conversation = Conversation.objects.get(id=CONVERSATION_ID)
    print(f"[OK] Conversation found:")
    print(f"  Title: {conversation.title}")
    print(f"  Created: {conversation.created_at}")
    print(f"  Document: {conversation.document_id}")
except Conversation.DoesNotExist:
    print(f"[ERROR] Conversation {CONVERSATION_ID} not found!")
    # List available conversations
    print("\n  Available conversations:")
    for c in Conversation.objects.all().order_by("-created_at")[:5]:
        print(f"    id={c.id} title={c.title} mode={c.mode}")
    sys.exit(1)

# ---------------------------------------------------------------------------
# 5b. Get all messages
# ---------------------------------------------------------------------------
print("\n" + "-" * 70)
print("5b: MESSAGES IN CONVERSATION")
print("-" * 70)

messages = Message.objects.filter(conversation=conversation).order_by("created_at")
print(f"  Total messages: {messages.count()}")

for msg in messages:
    print(f"\n  [{msg.created_at}] role={msg.role}")
    print(f"    content: {msg.content[:200]}...")
    
    # Check if this message has hub_metadata
    if hasattr(msg, 'hub_metadata') and msg.hub_metadata:
        print(f"    HAS HUB METADATA:")
        try:
            meta = msg.hub_metadata
            if isinstance(meta, str):
                meta = json.loads(meta)
            print(f"    {json.dumps(meta, indent=4, ensure_ascii=False)[:1000]}")
        except Exception as e:
            print(f"    (error parsing: {e})")
            print(f"    raw: {str(msg.hub_metadata)[:500]}")
    
    # Check for sources
    if hasattr(msg, 'sources') and msg.sources:
        print(f"    HAS SOURCES:")
        try:
            sources = msg.sources
            if isinstance(sources, str):
                sources = json.loads(sources)
            for i, src in enumerate(sources):
                print(f"    [{i+1}] {json.dumps(src, ensure_ascii=False)[:300]}")
        except Exception as e:
            print(f"    (error parsing: {e})")
            print(f"    raw: {str(msg.sources)[:500]}")

# ---------------------------------------------------------------------------
# 5c. Detailed hub_metadata breakdown
# ---------------------------------------------------------------------------
print("\n" + "-" * 70)
print("5c: DETAILED HUB METADATA BREAKDOWN")
print("-" * 70)

assistant_msg = messages.filter(role="assistant").first()
if assistant_msg and assistant_msg.hub_metadata:
    meta = assistant_msg.hub_metadata
    if isinstance(meta, str):
        meta = json.loads(meta)
    
    for hub_name, hub_data in meta.items():
        if not isinstance(hub_data, dict):
            continue
        print(f"\n  Hub: {hub_name}")
        print(f"    chunks_count: {hub_data.get('chunks_count')}")
        print(f"    error: {hub_data.get('error')}")
        
        sub_query = hub_data.get("sub_query", {})
        if sub_query:
            print(f"    fts_query: {sub_query.get('fts_query', '')[:100]}")
            print(f"    vector_query: {sub_query.get('vector_query', '')[:100]}")
        
        partial = hub_data.get("partial_answer", "")
        if partial:
            print(f"    partial_answer: {partial[:300]}")
        
        token_usage = hub_data.get("partial_answer_token_usage", {})
        if token_usage:
            print(f"    token_usage: {token_usage}")

# ---------------------------------------------------------------------------
# 5d. Detailed sources breakdown
# ---------------------------------------------------------------------------
print("\n" + "-" * 70)
print("5d: DETAILED SOURCES BREAKDOWN")
print("-" * 70)

if assistant_msg and assistant_msg.sources:
    sources = assistant_msg.sources
    if isinstance(sources, str):
        sources = json.loads(sources)
    
    for i, src in enumerate(sources):
        print(f"\n  Source [{i+1}]:")
        print(f"    hub_type: {src.get('hub_type')}")
        print(f"    chunk_id: {src.get('chunk_id')}")
        print(f"    content_preview: {src.get('content_preview', '')[:200]}")
        print(f"    page: {src.get('page_start')}-{src.get('page_end')}")

print("\n" + "=" * 70)
print("STEP 5 COMPLETE")
print("=" * 70)
