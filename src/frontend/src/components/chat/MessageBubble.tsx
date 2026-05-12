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
  Scale,
  Gavel,
  BookOpen,
  AlertTriangle,
} from 'lucide-react';
import type { Message, PartialAnswer } from '@/api/conversations';

// ── Types ──────────────────────────────────────────────────────────────────

interface MessageBubbleProps {
  message: Message;
  isStreaming?: boolean;
}

// ── Hub Configuration ──────────────────────────────────────────────────────

interface HubConfig {
  label: string;
  icon: React.ReactNode;
  color: string;       // Tailwind border color
  bgColor: string;     // Tailwind background color
  badgeColor: string;  // Tailwind text color for badge
}

const HUB_CONFIG: Record<string, HubConfig> = {
  legislation: {
    label: 'قوانین مصوب',
    icon: <Scale className="h-3.5 w-3.5" />,
    color: 'border-blue-400 dark:border-blue-600',
    bgColor: 'bg-blue-50 dark:bg-blue-950/30',
    badgeColor: 'text-blue-700 dark:text-blue-300',
  },
  judicial_precedent: {
    label: 'رویه‌های قضایی',
    icon: <Gavel className="h-3.5 w-3.5" />,
    color: 'border-emerald-400 dark:border-emerald-600',
    bgColor: 'bg-emerald-50 dark:bg-emerald-950/30',
    badgeColor: 'text-emerald-700 dark:text-emerald-300',
  },
  advisory_opinion: {
    label: 'نظریات مشورتی',
    icon: <BookOpen className="h-3.5 w-3.5" />,
    color: 'border-orange-400 dark:border-orange-600',
    bgColor: 'bg-orange-50 dark:bg-orange-950/30',
    badgeColor: 'text-orange-700 dark:text-orange-300',
  },
};

function getHubConfig(hubType: string): HubConfig {
  return HUB_CONFIG[hubType] ?? {
    label: hubType,
    icon: <FileText className="h-3.5 w-3.5" />,
    color: 'border-gray-400 dark:border-gray-600',
    bgColor: 'bg-gray-50 dark:bg-gray-950/30',
    badgeColor: 'text-gray-700 dark:text-gray-300',
  };
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
  messageId: string;
}

function SourceCitations({ sources, messageId }: SourceCitationsProps) {
  const [open, setOpen] = useState(false);
  const sourcesId = `sources-${messageId}`;

  return (
    <Collapsible open={open} onOpenChange={setOpen} className="pt-2">
      <CollapsibleTrigger
        className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground transition-colors"
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
        className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground transition-colors"
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
          const config = getHubConfig(hubType);
          const hasError = pa.error != null;

          return (
            <Card
              key={hubType}
              className={`border-l-4 ${config.color} ${config.bgColor}`}
            >
              <CardContent className="p-3 space-y-2">
                {/* Hub header */}
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-1.5 text-xs font-semibold">
                    {config.icon}
                    <span className={config.badgeColor}>{config.label}</span>
                  </div>

                  {/* Token usage badge */}
                  {pa.token_usage && pa.token_usage.total_tokens > 0 && (
                    <span className="text-[10px] text-muted-foreground/60">
                      {pa.token_usage.total_tokens} tokens
                    </span>
                  )}
                </div>

                {/* Error banner */}
                {hasError && (
                  <div className="flex items-start gap-1.5 rounded-md bg-destructive/10 p-2">
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
    <div className={cn('flex', isUser ? 'justify-end' : 'justify-start')}>
      <div
        className={cn(
          'flex flex-col max-w-[80%]',
          isUser ? 'items-end' : 'items-start',
        )}
        aria-label={isUser ? 'Your message' : 'AI response'}
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
