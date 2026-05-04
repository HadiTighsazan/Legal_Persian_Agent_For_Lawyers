# Task 4 — MessageBubble Component Implementation Plan

**Epic:** E10 — Frontend Chat Interface  
**PRD:** [`docs/active-task/current-prd.md`](docs/active-task/current-prd.md)  
**Implementation Plan:** [`docs/active-task/implementation-plan-e10.md`](docs/active-task/implementation-plan-e10.md)  
**Depends On:** Nothing (pure presentational component)  
**Test Type:** Visual First — Manual UI verification only

---

## Overview

Create the [`MessageBubble.tsx`](src/frontend/src/components/chat/MessageBubble.tsx) component — a pure presentational component that renders a single chat message. It handles two distinct visual modes (user vs. assistant), markdown rendering, streaming indicator, collapsible source citations, token usage display, and timestamp.

---

## Data Types (already defined in [`src/frontend/src/api/conversations.ts`](src/frontend/src/api/conversations.ts))

```typescript
interface Message {
  id: string;
  role: 'user' | 'assistant' | 'system';
  content: string;
  sources: MessageSource[];
  token_usage: TokenUsage | null;
  created_at: string;
}

interface MessageSource {
  chunk_id: string;
  page_start: number;
  page_end: number;
  content_preview?: string;
  relevance_score: number;
}

interface TokenUsage {
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
}
```

---

## Component Props

```typescript
interface MessageBubbleProps {
  message: Message;
  isStreaming?: boolean;  // default: false — shows blinking cursor for assistant
}
```

---

## Execution Steps

### Step 1: Install `react-markdown`

Run inside the running container:

```bash
docker-compose exec frontend npm install react-markdown
```

This adds `react-markdown` to `package.json` dependencies. No `remark-gfm` needed unless we want GitHub-flavored tables/strikethrough — the basic markdown renderer suffices for this task.

### Step 2: Create the Collapsible shadcn/ui component

Since [`Collapsible`](https://ui.shadcn.com/docs/components/collapsible) is not yet installed (confirmed by search), we need to add it. The shadcn/ui Collapsible is a thin wrapper around `@radix-ui/react-collapsible`.

**Option A (recommended):** Manually create the component file at [`src/frontend/src/components/ui/collapsible.tsx`](src/frontend/src/components/ui/collapsible.tsx) following the shadcn/ui pattern, since `npx shadcn-ui add collapsible` may not work in the containerized environment.

The Collapsible component needs:
- `Collapsible` root (from `@radix-ui/react-collapsible`)
- `CollapsibleTrigger` — the clickable toggle
- `CollapsibleContent` — the collapsible content area

We'll need to install `@radix-ui/react-collapsible`:

```bash
docker-compose exec frontend npm install @radix-ui/react-collapsible
```

### Step 3: Implement [`MessageBubble.tsx`](src/frontend/src/components/chat/MessageBubble.tsx)

#### 3a — File structure

```
src/frontend/src/components/chat/MessageBubble.tsx
```

#### 3b — Imports

```typescript
import { useState } from 'react';
import ReactMarkdown from 'react-markdown';
import { cn } from '@/lib/utils';
import {
  Collapsible,
  CollapsibleTrigger,
  CollapsibleContent,
} from '@/components/ui/collapsible';
import {
  Card,
  CardContent,
} from '@/components/ui/card';
import { ChevronDown, ChevronRight, FileText } from 'lucide-react';
import type { Message } from '@/api/conversations';
```

#### 3c — Component logic

**User message (`role === 'user'`):**
- Right-aligned bubble
- `bg-primary text-primary-foreground` colors
- `rounded-2xl rounded-tr-none` shape (top-right corner flat — speech bubble style)
- Max width ~70-80% of container
- Content rendered as plain text (no markdown needed for user messages)
- Timestamp below, right-aligned, `text-xs text-muted-foreground`

**Assistant message (`role === 'assistant'`):**
- Left-aligned, full width
- Content rendered via `<ReactMarkdown>` with prose styling (`prose prose-sm dark:prose-invert`)
- If `isStreaming === true`: append blinking cursor `▌` at the end of content
- Source citations section (collapsible) — only shown if `sources.length > 0`
- Token usage — tiny muted text — only shown if `token_usage !== null`
- Timestamp below, left-aligned, `text-xs text-muted-foreground`

#### 3d — Source citations sub-component

Each source renders as a [`Card`](src/frontend/src/components/ui/card.tsx) with:
- **Header:** `FileText` icon + "Source from page {page_start}–{page_end}"
- **Content:** `content_preview` text (truncated if long)
- **Footer:** Relevance score as a small badge (e.g., `{(relevance_score * 100).toFixed(0)}% match`)
- The entire sources section is wrapped in `Collapsible`:
  - Trigger text: `{sources.length} source{sources.length > 1 ? 's' : ''}` with `ChevronDown`/`ChevronRight` icon
  - Content: list of source `Card` components

#### 3e — Timestamp formatting

```typescript
function formatTime(dateString: string): string {
  const date = new Date(dateString);
  return date.toLocaleTimeString('en-US', {
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,  // HH:mm format
  });
}
```

#### 3f — Blinking cursor animation

Add a CSS keyframe animation in the component (via Tailwind or inline style):

```css
@keyframes blink {
  0%, 100% { opacity: 1; }
  50% { opacity: 0; }
}
```

Or use Tailwind's `animate-pulse` on the cursor character `▌`.

#### 3g — Component skeleton

```tsx
export default function MessageBubble({ message, isStreaming = false }: MessageBubbleProps) {
  const isUser = message.role === 'user';

  return (
    <div className={cn('flex', isUser ? 'justify-end' : 'justify-start')}>
      <div className={cn(
        'max-w-[80%] space-y-1',
        isUser ? 'items-end' : 'items-start',
      )}>
        {/* Bubble */}
        <div className={cn(
          'px-4 py-2.5',
          isUser
            ? 'bg-primary text-primary-foreground rounded-2xl rounded-tr-none'
            : 'w-full',
        )}>
          {isUser ? (
            <p className="text-sm whitespace-pre-wrap">{message.content}</p>
          ) : (
            <div className="prose prose-sm dark:prose-invert max-w-none">
              <ReactMarkdown>{message.content}</ReactMarkdown>
              {isStreaming && (
                <span className="animate-pulse ml-0.5">▌</span>
              )}
            </div>
          )}
        </div>

        {/* Footer: timestamp + token usage */}
        <div className={cn(
          'flex items-center gap-2 px-1',
          isUser ? 'justify-end' : 'justify-start',
        )}>
          <span className="text-xs text-muted-foreground">
            {formatTime(message.created_at)}
          </span>
          {message.token_usage && !isUser && (
            <span className="text-[10px] text-muted-foreground/60">
              {message.token_usage.total_tokens} tokens
            </span>
          )}
        </div>

        {/* Source citations (assistant only) */}
        {!isUser && message.sources.length > 0 && (
          <SourceCitations sources={message.sources} />
        )}
      </div>
    </div>
  );
}
```

### Step 4: Create a test page for visual verification

Since this is **Visual First**, create a temporary route or a simple test harness page to render the component with mock props. The developer can view it in the browser to verify styling.

**Option:** Create a temporary test page at [`src/frontend/src/pages/MessageBubbleTestPage.tsx`](src/frontend/src/pages/MessageBubbleTestPage.tsx) with mock data for:
- A user message
- An assistant message with markdown content (headings, lists, code, bold)
- An assistant message with sources
- An assistant message with streaming indicator
- An assistant message with token usage

This page can be temporarily mounted in [`App.tsx`](src/frontend/src/App.tsx) for visual verification, then removed after approval.

### Step 5: Update [`wip-context.md`](docs/active-task/wip-context.md)

After completion, update the WIP file with:
1. What was completed (MessageBubble component created)
2. Current state (component ready, visually verified)
3. Next step (proceed to Task 5 — MessageInput)

---

## Visual Design Specifications

### User Message Bubble
```
┌──────────────────────────────────┐
│                                  │
│   What is the main topic of      │
│   chapter 3?                     │
│                                  │
│                    14:32   │
└──────────────────────────────────┘
  ← left edge of container    ↑ right-aligned
```

### Assistant Message
```
┌─────────────────────────────────────┐
│                                     │
│  The main topic of chapter 3 is     │
│  **machine learning fundamentals**,  │
│  including:                         │
│                                     │
│  - Supervised learning              │
│  - Unsupervised learning            │
│  - Reinforcement learning           │
│                                     │
│  [See full explanation...]          │
│                                     │
│  14:32   ·   1,234 tokens           │
│                                     │
│  ▼ 3 sources                        │
│  ┌─────────────────────────────┐    │
│  │ 📄 Source from page 42–45   │    │
│  │ Machine learning is a       │    │
│  │ subset of artificial...     │    │
│  │                   92% match │    │
│  └─────────────────────────────┘    │
│  ┌─────────────────────────────┐    │
│  │ 📄 Source from page 50–52   │    │
│  │ The three main paradigms    │    │
│  │ of machine learning are...  │    │
│  │                   87% match │    │
│  └─────────────────────────────┘    │
│  ┌─────────────────────────────┐    │
│  │ 📄 Source from page 12–14   │    │
│  │ In this chapter we will    │    │
│  │ explore the foundational... │    │
│  │                   76% match │    │
│  └─────────────────────────────┘    │
└─────────────────────────────────────┘
  ↑ left-aligned, full width
```

### Streaming State
```
The main topic of chapter 3 is machine learning funda▌
                                                    ↑ blinking
```

---

## Files to Create

| # | File | Purpose |
|---|------|---------|
| 1 | `src/frontend/src/components/ui/collapsible.tsx` | shadcn/ui Collapsible component (Radix-based) |
| 2 | `src/frontend/src/components/chat/MessageBubble.tsx` | Main MessageBubble component |
| 3 | `src/frontend/src/pages/MessageBubbleTestPage.tsx` | Temporary test harness for visual verification |

## Files to Modify

| # | File | Change |
|---|------|--------|
| 1 | `src/frontend/package.json` | Add `react-markdown` and `@radix-ui/react-collapsible` dependencies |
| 2 | `src/frontend/src/App.tsx` | Temporarily add test page route for visual verification (revert after approval) |
| 3 | `docs/active-task/wip-context.md` | Update with completion status |

## Commands to Run

```bash
# Step 1: Install react-markdown
docker-compose exec frontend npm install react-markdown

# Step 2: Install @radix-ui/react-collapsible
docker-compose exec frontend npm install @radix-ui/react-collapsible
```

---

## Acceptance Criteria

1. ✅ User messages render as right-aligned blue bubbles with `rounded-2xl rounded-tr-none`
2. ✅ Assistant messages render left-aligned with full-width markdown content
3. ✅ Markdown content (headings, lists, code, bold, links) renders correctly via `react-markdown`
4. ✅ Blinking cursor `▌` appears at end of assistant content when `isStreaming={true}`
5. ✅ Source citations are collapsible, showing count in toggle text
6. ✅ Each source shows page range, relevance score, and content preview inside a `Card`
7. ✅ Token usage displays as tiny muted text when `token_usage` is provided
8. ✅ Timestamp displays in `HH:mm` format
9. ✅ No automated tests written (Visual First approach)
10. ✅ Component is pure presentational — no side effects, no API calls
