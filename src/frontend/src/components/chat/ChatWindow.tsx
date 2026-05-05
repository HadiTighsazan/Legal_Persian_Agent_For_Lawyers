import { useRef, useEffect, useCallback } from 'react';
import { useConversationStore } from '@/stores/conversationStore';
import { cn } from '@/lib/utils';
import { MessageSquare, AlertCircle, X } from 'lucide-react';
import { Alert, AlertTitle, AlertDescription } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import MessageBubble from '@/components/chat/MessageBubble';
import MessageInput from '@/components/chat/MessageInput';

// ── Types ──────────────────────────────────────────────────────────────────

interface ChatWindowProps {
  conversationId: string;
}

// ── Constants ──────────────────────────────────────────────────────────────

const STARTER_QUESTIONS = [
  'Summarize this document',
  'What are the key findings?',
  'Explain the main concepts',
] as const;

// ── Skeleton Sub-Component ─────────────────────────────────────────────────

function ChatSkeleton() {
  return (
    <div className="flex-1 space-y-4 p-4 overflow-hidden">
      {[1, 2, 3, 4].map((i) => (
        <div
          key={i}
          className={cn(
            'flex',
            i % 2 === 0 ? 'justify-end' : 'justify-start',
          )}
        >
          <div
            className={cn(
              'h-16 rounded-2xl bg-muted animate-pulse',
              i % 2 === 0 ? 'w-2/3 rounded-tr-none' : 'w-4/5',
            )}
          />
        </div>
      ))}
    </div>
  );
}

// ── Starter Chips Sub-Component ────────────────────────────────────────────

interface StarterChipsProps {
  onSend: (content: string) => void;
}

function StarterChips({ onSend }: StarterChipsProps) {
  return (
    <div className="mt-6 flex flex-wrap justify-center gap-2">
      {STARTER_QUESTIONS.map((question) => (
        <Button
          key={question}
          variant="outline"
          size="sm"
          onClick={() => onSend(question)}
          className="rounded-full text-xs"
          aria-label={`Ask: ${question}`}
        >
          {question}
        </Button>
      ))}
    </div>
  );
}

// ── Empty State Sub-Component ──────────────────────────────────────────────

interface EmptyStateProps {
  onSend: (content: string) => void;
}

function EmptyState({ onSend }: EmptyStateProps) {
  return (
    <div className="flex-1 flex flex-col items-center justify-center px-6 text-center">
      <MessageSquare className="h-12 w-12 text-muted-foreground mb-4" />
      <h2 className="text-xl font-semibold tracking-tight">
        Ask your first question
      </h2>
      <p className="mt-1 text-sm text-muted-foreground max-w-sm">
        Start a conversation about this document. The AI will answer based on
        the document content.
      </p>
      <StarterChips onSend={onSend} />
    </div>
  );
}

// ── Error Alert Sub-Component ──────────────────────────────────────────────

interface ErrorAlertProps {
  message: string;
  onRetry: () => void;
  onDismiss: () => void;
}

function ErrorAlert({ message, onRetry, onDismiss }: ErrorAlertProps) {
  return (
    <Alert variant="destructive" className="mx-4 mb-2">
      <AlertCircle className="h-4 w-4" />
      <AlertTitle>Error</AlertTitle>
      <AlertDescription className="flex items-center justify-between">
        <span>{message}</span>
        <div className="flex gap-2 shrink-0">
          <Button variant="outline" size="sm" onClick={onRetry}>
            Try Again
          </Button>
          <Button variant="ghost" size="sm" onClick={onDismiss} aria-label="Dismiss error">
            <X className="h-4 w-4" />
          </Button>
        </div>
      </AlertDescription>
    </Alert>
  );
}

// ── Main Component ─────────────────────────────────────────────────────────

export default function ChatWindow({ conversationId }: ChatWindowProps) {
  const activeConversation = useConversationStore((s) => s.activeConversation);
  const isLoadingMessages = useConversationStore((s) => s.isLoadingMessages);
  const isSendingMessage = useConversationStore((s) => s.isSendingMessage);
  const error = useConversationStore((s) => s.error);
  const loadConversation = useConversationStore((s) => s.loadConversation);
  const sendMessage = useConversationStore((s) => s.sendMessage);
  const sendMessageStream = useConversationStore((s) => s.sendMessageStream);
  const clearError = useConversationStore((s) => s.clearError);

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const lastAttemptedContent = useRef<string>('');

  const messages = activeConversation?.messages ?? [];

  // Load conversation on mount / conversationId change
  useEffect(() => {
    loadConversation(conversationId);
  }, [conversationId, loadConversation]);

  // Auto-scroll to bottom when messages change or sending state changes
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages.length, isSendingMessage]);

  const handleSend = useCallback(
    async (content: string) => {
      lastAttemptedContent.current = content;
      // Use streaming if available, fall back to non-streaming
      try {
        await sendMessageStream(conversationId, content);
      } catch {
        await sendMessage(conversationId, content);
      }
    },
    [conversationId, sendMessageStream, sendMessage],
  );

  const handleRetry = useCallback(async () => {
    if (lastAttemptedContent.current) {
      try {
        await sendMessageStream(conversationId, lastAttemptedContent.current);
      } catch {
        await sendMessage(conversationId, lastAttemptedContent.current);
      }
    }
  }, [conversationId, sendMessageStream, sendMessage]);

  // ── Render ─────────────────────────────────────────────────────────────

  return (
    <div className="flex flex-col h-full">
      {/* Message area */}
      {isLoadingMessages ? (
        <ChatSkeleton />
      ) : messages.length === 0 ? (
        <EmptyState onSend={handleSend} />
      ) : (
        <div
          className="flex-1 overflow-y-auto p-4 space-y-4"
          role="log"
          aria-live="polite"
          aria-busy={isSendingMessage}
        >
          {messages.map((msg, index) => (
            <MessageBubble
              key={msg.id}
              message={msg}
              isStreaming={
                index === messages.length - 1 &&
                msg.role === 'assistant' &&
                isSendingMessage
              }
            />
          ))}
          <div ref={messagesEndRef} />
        </div>
      )}

      {/* Error alert (non-blocking, above input) */}
      {error && (
        <ErrorAlert
          message={error}
          onRetry={handleRetry}
          onDismiss={clearError}
        />
      )}

      {/* Input */}
      <MessageInput
        onSend={handleSend}
        isDisabled={isSendingMessage}
      />
    </div>
  );
}
