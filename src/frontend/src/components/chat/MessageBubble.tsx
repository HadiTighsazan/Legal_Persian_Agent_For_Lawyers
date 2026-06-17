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
import {
  ChevronDown,
  ChevronRight,
  FileText,
  AlertTriangle,
  User,
  Zap,
} from 'lucide-react';
import HubStatusBadge from '@/components/rag/HubStatusBadge';
import type { Message, PartialAnswer } from '@/api/conversations';

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


// ── Token Usage Badge ──────────────────────────────────────────────────────

interface TokenUsageData {
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
}

interface TokenBadgeProps {
  tokenUsage: TokenUsageData;
  /** Show detailed breakdown (prompt → completion → total). Default: false */
  detailed?: boolean;
}

function formatTokenCount(count: number): string {
  if (count >= 1000) {
    return `${(count / 1000).toFixed(1)}k`;
  }
  return count.toLocaleString();
}

function TokenBadge({ tokenUsage, detailed = false }: TokenBadgeProps) {
  return (
    <span
      className="inline-flex items-center gap-1.5 rounded-full bg-muted/60 px-2.5 py-1 text-[11px] font-medium text-muted-foreground/80 hover:bg-muted/80 transition-colors cursor-default"
      title={`${tokenUsage.prompt_tokens.toLocaleString()} prompt tokens → ${tokenUsage.completion_tokens.toLocaleString()} completion tokens = ${tokenUsage.total_tokens.toLocaleString()} total`}
    >
      <Zap className="h-3 w-3 text-amber-500/70" />
      {detailed ? (
        <span>
          <span className="text-muted-foreground/60">↑</span>
          {formatTokenCount(tokenUsage.prompt_tokens)}{' '}
          <span className="text-muted-foreground/60">↓</span>
          {formatTokenCount(tokenUsage.completion_tokens)}{' '}
          <span className="text-muted-foreground/40">=</span>{' '}
          <span className="text-foreground/70">{formatTokenCount(tokenUsage.total_tokens)}</span>
        </span>
      ) : (
        <span>
          <span className="text-foreground/70">{formatTokenCount(tokenUsage.total_tokens)}</span>{' '}
          <span className="text-muted-foreground/50">tokens</span>
        </span>
      )}
    </span>
  );
}

// ── Source Citations Sub-Component ─────────────────────────────────────────

interface SourceCitationsProps {
  sources: Message['sources'];
  messageId: string;
}

function SourceCitations({ sources, messageId }: SourceCitationsProps) {
  const [open, setOpen] = useState(false);
  const sourcesId = `sources-${messageId}`;

  return (
    <Collapsible open={open} onOpenChange={setOpen} className="pt-2">
      <CollapsibleTrigger
        className="flex items-center gap-1 text-xs text-muted-foreground/70 hover:text-foreground transition-colors"
        aria-expanded={open}
        aria-controls={sourcesId}
      >
        {open ? (
          <ChevronDown className="h-3 w-3" />
        ) : (
          <ChevronRight className="h-3 w-3" />
        )}
        <span>
          {sources.length} source{sources.length > 1 ? 's' : ''}
        </span>
      </CollapsibleTrigger>
      <CollapsibleContent className="space-y-2 pt-2" id={sourcesId}>
        {sources.map((source) => (
          <Card key={source.chunk_id} className="border-border/60 shadow-none">
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
                <p className="text-xs text-muted-foreground/80 line-clamp-3 leading-relaxed" dir="auto">
                  {source.content_preview}
                </p>
              )}

              {/* Relevance score badge */}
              <div className="flex justify-end">
                <span className="inline-flex items-center rounded-full bg-primary/8 px-2 py-0.5 text-[10px] font-medium text-primary">
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

// ── Partial Answers Sub-Component ──────────────────────────────────────────

interface PartialAnswersSectionProps {
  partialAnswers: Record<string, PartialAnswer>;
  messageId: string;
}

function PartialAnswersSection({
  partialAnswers,
  messageId,
}: PartialAnswersSectionProps) {
  const [open, setOpen] = useState(false);
  const partialAnswersId = `partial-answers-${messageId}`;
  const hubTypes = Object.keys(partialAnswers);

  if (hubTypes.length === 0) return null;

  return (
    <Collapsible open={open} onOpenChange={setOpen} className="pt-3">
      <CollapsibleTrigger
        className="flex items-center gap-1 text-xs text-muted-foreground/70 hover:text-foreground transition-colors"
        aria-expanded={open}
        aria-controls={partialAnswersId}
      >
        {open ? (
          <ChevronDown className="h-3 w-3" />
        ) : (
          <ChevronRight className="h-3 w-3" />
        )}
        <span>Partial Answers ({hubTypes.length} hubs)</span>
      </CollapsibleTrigger>
      <CollapsibleContent className="space-y-2 pt-2" id={partialAnswersId}>
        {hubTypes.map((hubType) => {
          const pa = partialAnswers[hubType];
          const hasError = pa.error != null;

          return (
            <Card
              key={hubType}
              className="border-l-4 border-l-muted-foreground/20 shadow-none"
            >
              <CardContent className="p-3 space-y-2">
                {/* Hub header */}
                <div className="flex items-center justify-between">
                  <HubStatusBadge hubType={hubType} />

                  {/* Token usage badge */}
                  {pa.token_usage && pa.token_usage.total_tokens > 0 && (
                    <TokenBadge tokenUsage={pa.token_usage} />
                  )}
                </div>

                {/* Error banner */}
                {hasError && (
                  <div className="flex items-start gap-1.5 rounded-md bg-destructive/8 p-2">
                    <AlertTriangle className="h-3.5 w-3.5 text-destructive shrink-0 mt-0.5" />
                    <p className="text-xs text-destructive" dir="auto">
                      {pa.error}
                    </p>
                  </div>
                )}

                {/* Partial answer content */}
                {pa.content && (
                  <div className="text-xs text-muted-foreground leading-relaxed" dir="auto">
                    <ReactMarkdown
                      components={{
                        p: ({ children, ...rest }) => (
                          <p className="mb-1 last:mb-0" {...rest}>{children}</p>
                        ),
                      }}
                    >
                      {pa.content}
                    </ReactMarkdown>
                  </div>
                )}
              </CardContent>
            </Card>
          );
        })}
      </CollapsibleContent>
    </Collapsible>
  );
}

// ── AI Avatar ──────────────────────────────────────────────────────────────

function AiAvatar() {
  return (
    <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-primary/10">
      <Zap className="h-4 w-4 text-primary" />
    </div>
  );
}

// ── User Avatar ────────────────────────────────────────────────────────────

function UserAvatar() {
  return (
    <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-foreground/10">
      <User className="h-4 w-4 text-foreground/70" />
    </div>
  );
}

// ── Main Component ─────────────────────────────────────────────────────────

export default function MessageBubble({
  message,
  isStreaming = false,
}: MessageBubbleProps) {
  const isUser = message.role === 'user';
  const hasPartialAnswers =
    !isUser &&
    message.partial_answers != null &&
    Object.keys(message.partial_answers).length > 0;

  return (
    <div
      className={cn(
        'flex items-start gap-3 animate-message-in',
        isUser ? 'flex-row-reverse' : 'flex-row',
      )}
      aria-label={isUser ? 'Your message' : 'AI response'}
    >
      {/* Avatar */}
      {isUser ? <UserAvatar /> : <AiAvatar />}

      {/* Content column */}
      <div
        className={cn(
          'flex flex-col max-w-[75%]',
          isUser ? 'items-end' : 'items-start',
        )}
      >
        {/* Bubble */}
        {isUser ? (
          <div className="rounded-2xl rounded-br-sm bg-primary px-4 py-2.5 text-primary-foreground shadow-sm">
            <p className="text-sm whitespace-pre-wrap leading-relaxed" dir="auto">
              {message.content}
            </p>
          </div>
        ) : (
          <div className="w-full rounded-2xl border border-border/60 bg-card px-4 py-3 shadow-sm">
            <div className="prose-chat" dir="auto">
              <ReactMarkdown>{message.content}</ReactMarkdown>
              {isStreaming && (
                <span className="animate-pulse ml-0.5 text-primary">▌</span>
              )}
            </div>
          </div>
        )}

        {/* Footer: timestamp + token usage */}
        <div
          className={cn(
            'flex items-center gap-2 px-1 pt-1.5',
            isUser ? 'justify-end' : 'justify-start',
          )}
        >
          <span className="text-[11px] text-muted-foreground/50">
            {formatTime(message.created_at)}
          </span>
          {message.token_usage && !isUser && (
            <TokenBadge tokenUsage={message.token_usage} detailed />
          )}
        </div>

        {/* Source citations (assistant only) */}
        {!isUser && message.sources.length > 0 && (
          <SourceCitations sources={message.sources} messageId={message.id} />
        )}

        {/* Partial answers (assistant only, global_rag mode) */}
        {hasPartialAnswers && (
          <PartialAnswersSection
            partialAnswers={message.partial_answers!}
            messageId={message.id}
          />
        )}
      </div>
    </div>
  );
}
