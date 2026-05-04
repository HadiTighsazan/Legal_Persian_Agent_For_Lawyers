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

// ── Types ──────────────────────────────────────────────────────────────────

interface MessageBubbleProps {
  message: Message;
  isStreaming?: boolean;
}

// ── Helpers ────────────────────────────────────────────────────────────────

function formatTime(dateString: string): string {
  const date = new Date(dateString);
  return date.toLocaleTimeString('en-US', {
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  });
}

// ── Source Citations Sub-Component ─────────────────────────────────────────

interface SourceCitationsProps {
  sources: Message['sources'];
}

function SourceCitations({ sources }: SourceCitationsProps) {
  const [open, setOpen] = useState(false);

  return (
    <Collapsible open={open} onOpenChange={setOpen} className="pt-2">
      <CollapsibleTrigger className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground transition-colors">
        {open ? (
          <ChevronDown className="h-3 w-3" />
        ) : (
          <ChevronRight className="h-3 w-3" />
        )}
        <span>
          {sources.length} source{sources.length > 1 ? 's' : ''}
        </span>
      </CollapsibleTrigger>
      <CollapsibleContent className="space-y-2 pt-2">
        {sources.map((source) => (
          <Card key={source.chunk_id} className="border-muted">
            <CardContent className="p-3 space-y-1.5">
              {/* Header: icon + page range */}
              <div className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
                <FileText className="h-3.5 w-3.5" />
                <span>
                  Source from page {source.page_start}–{source.page_end}
                </span>
              </div>

              {/* Content preview */}
              {source.content_preview && (
                <p className="text-xs text-muted-foreground/80 line-clamp-3" dir="auto">
                  {source.content_preview}
                </p>
              )}

              {/* Relevance score badge */}
              <div className="flex justify-end">
                <span className="inline-flex items-center rounded-full bg-primary/10 px-2 py-0.5 text-[10px] font-medium text-primary">
                  {(source.relevance_score * 100).toFixed(0)}% match
                </span>
              </div>
            </CardContent>
          </Card>
        ))}
      </CollapsibleContent>
    </Collapsible>
  );
}

// ── Main Component ─────────────────────────────────────────────────────────

export default function MessageBubble({
  message,
  isStreaming = false,
}: MessageBubbleProps) {
  const isUser = message.role === 'user';

  return (
    <div className={cn('flex', isUser ? 'justify-end' : 'justify-start')}>
      <div
        className={cn(
          'flex flex-col max-w-[80%]',
          isUser ? 'items-end' : 'items-start',
        )}
      >
        {/* Bubble */}
        <div
          className={cn(
            'px-4 py-2.5',
            isUser
              ? 'bg-primary text-primary-foreground rounded-2xl rounded-tr-none'
              : 'w-full',
          )}
        >
          {isUser ? (
            <p className="text-sm whitespace-pre-wrap" dir="auto">{message.content}</p>
          ) : (
            <div className="prose prose-sm dark:prose-invert max-w-none" dir="auto">
              <ReactMarkdown>{message.content}</ReactMarkdown>
              {isStreaming && (
                <span className="animate-pulse ml-0.5">▌</span>
              )}
            </div>
          )}
        </div>

        {/* Footer: timestamp + token usage */}
        <div
          className={cn(
            'flex items-center gap-2 px-1 pt-1',
            isUser ? 'justify-end' : 'justify-start',
          )}
        >
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
