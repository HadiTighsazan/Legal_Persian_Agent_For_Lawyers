import { useEffect, useState } from 'react';
import { PlusIcon, Trash2, MessageSquare } from 'lucide-react';
import { cn } from '@/lib/utils';
import { Button } from '@/components/ui/button';
import { useConversationStore } from '@/stores/conversationStore';
import type { Conversation } from '@/api/conversations';

// ── Props ──────────────────────────────────────────────────────────────────

interface ConversationSidebarProps {
  documentId: string;
  activeConversationId: string | null;
  onSelect: (conversationId: string) => void;
}

// ── Helpers ─────────────────────────────────────────────────────────────────

function formatRelativeTime(dateString: string): string {
  const now = Date.now();
  const date = new Date(dateString).getTime();
  const diffMs = now - date;
  const diffSeconds = Math.floor(diffMs / 1000);
  const diffMinutes = Math.floor(diffSeconds / 60);
  const diffHours = Math.floor(diffMinutes / 60);
  const diffDays = Math.floor(diffHours / 24);

  if (diffSeconds < 60) return 'just now';
  if (diffMinutes < 60) return `${diffMinutes} minute${diffMinutes !== 1 ? 's' : ''} ago`;
  if (diffHours < 24) return `${diffHours} hour${diffHours !== 1 ? 's' : ''} ago`;
  if (diffDays < 30) return `${diffDays} day${diffDays !== 1 ? 's' : ''} ago`;
  return new Date(dateString).toLocaleDateString();
}

// ── Skeleton ────────────────────────────────────────────────────────────────

function ConversationSkeleton() {
  return (
    <>
      <div className="h-10 rounded-md bg-muted animate-pulse" />
      <div className="h-10 rounded-md bg-muted animate-pulse" />
      <div className="h-10 rounded-md bg-muted animate-pulse" />
    </>
  );
}

// ── Empty State ─────────────────────────────────────────────────────────────

function EmptyState() {
  return (
    <div className="flex flex-col items-center justify-center h-full text-sm text-muted-foreground p-4 text-center">
      <MessageSquare className="h-8 w-8 mb-2 opacity-40" />
      <p>No conversations yet.</p>
      <p className="mt-1">Start a new chat to begin.</p>
    </div>
  );
}

// ── Conversation Item ───────────────────────────────────────────────────────

interface ConversationItemProps {
  conversation: Conversation;
  isActive: boolean;
  confirmingDeleteId: string | null;
  onSelect: (id: string) => void;
  onDeleteClick: (id: string) => void;
  onConfirmDelete: (id: string) => void;
  onCancelDelete: () => void;
}

function ConversationItem({
  conversation,
  isActive,
  confirmingDeleteId,
  onSelect,
  onDeleteClick,
  onConfirmDelete,
  onCancelDelete,
}: ConversationItemProps) {
  const isConfirming = confirmingDeleteId === conversation.id;

  return (
    <div
      className={cn(
        'flex items-center justify-between rounded-md px-3 py-2 text-sm cursor-pointer group',
        isActive
          ? 'bg-primary/10 text-primary border-l-2 border-primary'
          : 'hover:bg-accent',
      )}
      onClick={() => {
        if (!isConfirming) {
          onSelect(conversation.id);
        }
      }}
    >
      {isConfirming ? (
        <div className="text-xs text-muted-foreground flex items-center gap-1 w-full">
          <span>Delete?</span>
          <button
            className="font-medium text-destructive hover:underline ml-auto"
            onClick={(e) => {
              e.stopPropagation();
              onConfirmDelete(conversation.id);
            }}
          >
            Yes
          </button>
          <span className="text-muted-foreground">/</span>
          <button
            className="font-medium hover:underline"
            onClick={(e) => {
              e.stopPropagation();
              onCancelDelete();
            }}
          >
            No
          </button>
        </div>
      ) : (
        <>
          <span className="truncate flex-1">
            {conversation.title || 'Untitled Chat'}
          </span>
          <span className="text-xs text-muted-foreground shrink-0 ml-2">
            {formatRelativeTime(conversation.updated_at)}
          </span>
          <button
            className="ml-1 opacity-0 group-hover:opacity-100 transition-opacity"
            onClick={(e) => {
              e.stopPropagation();
              onDeleteClick(conversation.id);
            }}
            aria-label={`Delete conversation ${conversation.title || 'Untitled Chat'}`}
          >
            <Trash2 className="h-4 w-4 text-muted-foreground hover:text-destructive" />
          </button>
        </>
      )}
    </div>
  );
}

// ── Main Component ──────────────────────────────────────────────────────────

export default function ConversationSidebar({
  documentId,
  activeConversationId,
  onSelect,
}: ConversationSidebarProps) {
  const [confirmingDeleteId, setConfirmingDeleteId] = useState<string | null>(null);

  const conversations = useConversationStore((state) => state.conversations);
  const isLoadingConversations = useConversationStore((state) => state.isLoadingConversations);
  const fetchConversations = useConversationStore((state) => state.fetchConversations);
  const createConversation = useConversationStore((state) => state.createConversation);
  const deleteConversation = useConversationStore((state) => state.deleteConversation);

  // ── Fetch conversations on mount ────────────────────────────────────────
  useEffect(() => {
    fetchConversations(documentId);
  }, [documentId, fetchConversations]);

  // ── Handlers ────────────────────────────────────────────────────────────

  const handleNewChat = async () => {
    try {
      const newConv = await createConversation(documentId);
      onSelect(newConv.id);
    } catch {
      // Error is handled by the store
    }
  };

  const handleDeleteClick = (id: string) => {
    setConfirmingDeleteId(id);
  };

  const handleConfirmDelete = async (id: string) => {
    setConfirmingDeleteId(null);
    try {
      await deleteConversation(id);
    } catch {
      // Error is handled by the store
    }
  };

  const handleCancelDelete = () => {
    setConfirmingDeleteId(null);
  };

  // ── Render ──────────────────────────────────────────────────────────────

  return (
    <div className="w-72 h-full border-r bg-background flex flex-col">
      {/* Header */}
      <div className="p-4 border-b space-y-3">
        <h2 className="text-sm font-semibold text-muted-foreground uppercase tracking-wider">
          Conversations
        </h2>
        <Button
          variant="outline"
          size="sm"
          className="w-full justify-start gap-2"
          onClick={handleNewChat}
        >
          <PlusIcon className="h-4 w-4" />
          New Chat
        </Button>
      </div>

      {/* List */}
      <div className="flex-1 overflow-y-auto p-2 space-y-1">
        {isLoadingConversations ? (
          <ConversationSkeleton />
        ) : conversations.length === 0 ? (
          <EmptyState />
        ) : (
          conversations.map((conv) => (
            <ConversationItem
              key={conv.id}
              conversation={conv}
              isActive={conv.id === activeConversationId}
              confirmingDeleteId={confirmingDeleteId}
              onSelect={onSelect}
              onDeleteClick={handleDeleteClick}
              onConfirmDelete={handleConfirmDelete}
              onCancelDelete={handleCancelDelete}
            />
          ))
        )}
      </div>
    </div>
  );
}
