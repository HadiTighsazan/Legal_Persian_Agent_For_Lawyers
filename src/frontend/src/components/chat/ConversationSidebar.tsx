import { useEffect, useState, useRef, useCallback } from 'react';
import { PlusIcon, Trash2, Pencil, MessageSquare, Check, X, Loader2, History } from 'lucide-react';
import { cn } from '@/lib/utils';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { useConversationStore } from '@/stores/conversationStore';
import { toast } from '@/hooks/use-toast';
import type { Conversation, RagMode } from '@/api/conversations';

// ── Props ──────────────────────────────────────────────────────────────────

interface ConversationSidebarProps {
  documentId?: string;
  activeConversationId: string | null;
  onSelect: (conversationId: string) => void;
  mode?: RagMode;
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
  if (diffMinutes < 60) return `${diffMinutes}m`;
  if (diffHours < 24) return `${diffHours}h`;
  if (diffDays < 30) return `${diffDays}d`;
  return new Date(dateString).toLocaleDateString();
}

// ── Skeleton ────────────────────────────────────────────────────────────────

function ConversationSkeleton() {
  return (
    <div className="space-y-1 px-2">
      {[1, 2, 3].map((i) => (
        <div key={i} className="h-10 rounded-lg bg-muted/60 shimmer" />
      ))}
    </div>
  );
}

// ── Empty State ─────────────────────────────────────────────────────────────

function EmptyState() {
  return (
    <div className="flex flex-col items-center justify-center h-full text-sm text-muted-foreground p-4 text-center">
      <History className="h-8 w-8 mb-2 opacity-30" />
      <p>No conversations yet.</p>
      <p className="mt-1 text-xs text-muted-foreground/60">Start a new chat to begin.</p>
    </div>
  );
}

// ── Conversation Item ───────────────────────────────────────────────────────

interface ConversationItemProps {
  conversation: Conversation;
  isActive: boolean;
  confirmingDeleteId: string | null;
  renamingId: string | null;
  onSelect: (id: string) => void;
  onDeleteClick: (id: string) => void;
  onConfirmDelete: (id: string) => void;
  onCancelDelete: () => void;
  onRenameStart: (id: string) => void;
  onRenameCancel: () => void;
  onRenameConfirm: (id: string, title: string) => void;
}

function ConversationItem({
  conversation,
  isActive,
  confirmingDeleteId,
  renamingId,
  onSelect,
  onDeleteClick,
  onConfirmDelete,
  onCancelDelete,
  onRenameStart,
  onRenameCancel,
  onRenameConfirm,
}: ConversationItemProps) {
  const isConfirming = confirmingDeleteId === conversation.id;
  const isRenaming = renamingId === conversation.id;
  const [editTitle, setEditTitle] = useState(conversation.title || '');
  const inputRef = useRef<HTMLInputElement>(null);

  // Focus input when rename starts
  useEffect(() => {
    if (isRenaming && inputRef.current) {
      inputRef.current.focus();
      inputRef.current.select();
    }
  }, [isRenaming]);

  // Reset edit title when conversation changes
  useEffect(() => {
    setEditTitle(conversation.title || '');
  }, [conversation.title]);

  const handleRenameSubmit = useCallback(() => {
    const trimmed = editTitle.trim();
    if (trimmed && trimmed !== (conversation.title || '')) {
      onRenameConfirm(conversation.id, trimmed);
    } else {
      onRenameCancel();
    }
  }, [editTitle, conversation.id, conversation.title, onRenameConfirm, onRenameCancel]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLInputElement>) => {
      if (e.key === 'Enter') {
        handleRenameSubmit();
      } else if (e.key === 'Escape') {
        onRenameCancel();
      }
    },
    [handleRenameSubmit, onRenameCancel],
  );

  if (isConfirming) {
    return (
      <div
        className={cn(
          'flex items-center justify-between rounded-lg px-3 py-2 text-sm',
          isActive ? 'bg-primary/8' : 'hover:bg-muted/50',
        )}
      >
        <span className="text-xs text-muted-foreground">Delete this chat?</span>
        <div className="flex items-center gap-1.5">
          <button
            className="text-xs font-medium text-destructive hover:text-destructive/80 transition-colors"
            onClick={(e) => {
              e.stopPropagation();
              onConfirmDelete(conversation.id);
            }}
          >
            Yes
          </button>
          <span className="text-muted-foreground/40">/</span>
          <button
            className="text-xs font-medium text-muted-foreground hover:text-foreground transition-colors"
            onClick={(e) => {
              e.stopPropagation();
              onCancelDelete();
            }}
          >
            No
          </button>
        </div>
      </div>
    );
  }

  return (
    <div
      className={cn(
        'group flex items-center justify-between rounded-lg px-3 py-2 text-sm cursor-pointer transition-all duration-150',
        isActive
          ? 'bg-primary/8 text-foreground font-medium'
          : 'hover:bg-muted/50 text-muted-foreground hover:text-foreground',
      )}
      role="button"
      aria-label={`Conversation: ${conversation.title || 'Untitled Chat'}`}
      onClick={() => {
        if (!isRenaming) {
          onSelect(conversation.id);
        }
      }}
    >
      {isRenaming ? (
        <div className="flex items-center gap-1 w-full" onClick={(e) => e.stopPropagation()}>
          <Input
            ref={inputRef}
            value={editTitle}
            onChange={(e) => setEditTitle(e.target.value)}
            onKeyDown={handleKeyDown}
            className="h-7 text-sm px-2 py-1"
            placeholder="Conversation title"
          />
          <button
            className="shrink-0 p-0.5 text-muted-foreground hover:text-foreground transition-colors"
            onClick={handleRenameSubmit}
            aria-label="Confirm rename"
          >
            <Check className="h-3.5 w-3.5" />
          </button>
          <button
            className="shrink-0 p-0.5 text-muted-foreground hover:text-foreground transition-colors"
            onClick={onRenameCancel}
            aria-label="Cancel rename"
          >
            <X className="h-3.5 w-3.5" />
          </button>
        </div>
      ) : (
        <>
          <div className="flex items-center gap-2 min-w-0 flex-1">
            <MessageSquare className="h-3.5 w-3.5 shrink-0 opacity-50" />
            <span className="truncate">{conversation.title || 'Untitled Chat'}</span>
          </div>
          <div className="flex items-center gap-0.5 shrink-0">
            <span className="text-[10px] text-muted-foreground/40 mr-1">
              {formatRelativeTime(conversation.updated_at)}
            </span>
            <button
              className="opacity-0 group-hover:opacity-100 transition-opacity p-0.5 rounded hover:bg-muted/80"
              onClick={(e) => {
                e.stopPropagation();
                onRenameStart(conversation.id);
              }}
              aria-label={`Rename conversation ${conversation.title || 'Untitled Chat'}`}
            >
              <Pencil className="h-3 w-3 text-muted-foreground/60 hover:text-foreground" />
            </button>
            <button
              className="opacity-0 group-hover:opacity-100 transition-opacity p-0.5 rounded hover:bg-muted/80"
              onClick={(e) => {
                e.stopPropagation();
                onDeleteClick(conversation.id);
              }}
              aria-label={`Delete conversation ${conversation.title || 'Untitled Chat'}`}
            >
              <Trash2 className="h-3 w-3 text-muted-foreground/60 hover:text-destructive" />
            </button>
          </div>
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
  mode,
}: ConversationSidebarProps) {
  const [confirmingDeleteId, setConfirmingDeleteId] = useState<string | null>(null);
  const [renamingId, setRenamingId] = useState<string | null>(null);

  const conversations = useConversationStore((state) => state.conversations);
  const isLoadingConversations = useConversationStore((state) => state.isLoadingConversations);
  const isCreatingConversation = useConversationStore((state) => state.isCreatingConversation);
  const fetchConversations = useConversationStore((state) => state.fetchConversations);
  const createConversation = useConversationStore((state) => state.createConversation);
  const deleteConversation = useConversationStore((state) => state.deleteConversation);
  const renameConversation = useConversationStore((state) => state.renameConversation);

  // ── Fetch conversations on mount ────────────────────────────────────────
  useEffect(() => {
    fetchConversations(documentId, mode);
  }, [documentId, mode, fetchConversations]);

  // ── Handlers ────────────────────────────────────────────────────────────

  const handleNewChat = async () => {
    try {
      const newConv = await createConversation(documentId, undefined, mode);
      onSelect(newConv.id);
    } catch {
      toast({
        title: 'Error',
        description: 'Failed to create a new conversation. Please try again.',
        variant: 'destructive',
      });
    }
  };

  const handleDeleteClick = (id: string) => {
    setConfirmingDeleteId(id);
    setRenamingId(null);
  };

  const handleConfirmDelete = async (id: string) => {
    setConfirmingDeleteId(null);
    try {
      await deleteConversation(id);
    } catch {
      toast({
        title: 'Error',
        description: 'Failed to delete conversation. Please try again.',
        variant: 'destructive',
      });
    }
  };

  const handleCancelDelete = () => {
    setConfirmingDeleteId(null);
  };

  const handleRenameStart = (id: string) => {
    setRenamingId(id);
    setConfirmingDeleteId(null);
  };

  const handleRenameCancel = () => {
    setRenamingId(null);
  };

  const handleRenameConfirm = async (id: string, title: string) => {
    setRenamingId(null);
    try {
      await renameConversation(id, title);
    } catch {
      toast({
        title: 'Error',
        description: 'Failed to rename conversation. Please try again.',
        variant: 'destructive',
      });
    }
  };

  // ── Render ──────────────────────────────────────────────────────────────

  return (
    <div
      className="h-full bg-background flex flex-col"
      role="navigation"
      aria-label="Conversations"
    >
      {/* Header */}
      <div className="p-3 border-b border-border/60 space-y-2">
        <h2 className="text-xs font-semibold text-muted-foreground/60 uppercase tracking-wider px-1">
          Conversations
        </h2>
        <Button
          variant="outline"
          size="sm"
          className="w-full justify-start gap-2 rounded-lg border-border/60 hover:bg-muted/50"
          onClick={handleNewChat}
          disabled={isCreatingConversation}
          aria-label="Create new conversation"
        >
          {isCreatingConversation ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <PlusIcon className="h-4 w-4" />
          )}
          {isCreatingConversation ? 'Creating...' : 'New Chat'}
        </Button>
      </div>

      {/* List */}
      <div className="flex-1 overflow-y-auto p-2 space-y-0.5">
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
              renamingId={renamingId}
              onSelect={onSelect}
              onDeleteClick={handleDeleteClick}
              onConfirmDelete={handleConfirmDelete}
              onCancelDelete={handleCancelDelete}
              onRenameStart={handleRenameStart}
              onRenameCancel={handleRenameCancel}
              onRenameConfirm={handleRenameConfirm}
            />
          ))
        )}
      </div>
    </div>
  );
}
