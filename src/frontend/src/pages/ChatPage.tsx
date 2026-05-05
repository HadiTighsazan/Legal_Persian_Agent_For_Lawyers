import { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import {
  ArrowLeft,
  MessageSquare,
  PlusIcon,
  PanelLeftClose,
  PanelLeft,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import ConversationSidebar from '@/components/chat/ConversationSidebar';
import ChatWindow from '@/components/chat/ChatWindow';
import ChatErrorBoundary from '@/components/chat/ChatErrorBoundary';
import { useConversationStore } from '@/stores/conversationStore';
import { apiClient } from '@/api/axios';

// ── NoConversationSelected Sub-Component ──────────────────────────────────

function NoConversationSelected({ documentId }: { documentId: string }) {
  const navigate = useNavigate();
  const createConversation = useConversationStore((s) => s.createConversation);

  const handleNewChat = async () => {
    try {
      const conv = await createConversation(documentId);
      navigate(`/documents/${documentId}/chat/${conv.id}`, { replace: true });
    } catch {
      // Error handled by store
    }
  };

  return (
    <div className="flex-1 flex flex-col items-center justify-center px-6 text-center">
      <MessageSquare className="h-16 w-16 text-muted-foreground mb-4" />
      <h2 className="text-2xl font-semibold tracking-tight">
        Document Chat
      </h2>
      <p className="mt-2 text-sm text-muted-foreground max-w-md">
        Start a new conversation or select an existing one from the sidebar to
        ask questions about this document.
      </p>
      <Button className="mt-6 gap-2" onClick={handleNewChat}>
        <PlusIcon className="h-4 w-4" />
        Start New Chat
      </Button>
    </div>
  );
}

// ── Main Component ────────────────────────────────────────────────────────

export default function ChatPage() {
  const { documentId, conversationId } = useParams<{
    documentId: string;
    conversationId?: string;
  }>();
  const navigate = useNavigate();

  // Mobile sidebar drawer state
  const [sidebarOpen, setSidebarOpen] = useState(false);

  // Desktop sidebar collapse state
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);

  // Document title (for when no conversation is active)
  const [documentTitle, setDocumentTitle] = useState<string | null>(null);

  const activeConversation = useConversationStore(
    (s) => s.activeConversation,
  );

  // Fetch document title when no conversation is active
  useEffect(() => {
    if (activeConversation?.document_title) {
      setDocumentTitle(activeConversation.document_title);
    } else if (documentId) {
      apiClient
        .get<{ title: string }>(`documents/${documentId}/`)
        .then((res) => setDocumentTitle(res.data.title))
        .catch(() => setDocumentTitle(null));
    }
  }, [documentId, activeConversation?.document_title]);

  // Dynamic page title
  useEffect(() => {
    const title = documentTitle
      ? `Chat — ${documentTitle} | DocuChat`
      : 'Chat | DocuChat';
    document.title = title;

    // Cleanup: restore default title on unmount
    return () => {
      document.title = 'DocuChat';
    };
  }, [documentTitle]);

  // ── Handlers ──────────────────────────────────────────────────────────

  const handleSidebarSelect = (id: string) => {
    navigate(`/documents/${documentId}/chat/${id}`);
    setSidebarOpen(false);
  };

  const handleDesktopSelect = (id: string) => {
    navigate(`/documents/${documentId}/chat/${id}`);
  };

  // ── Render ────────────────────────────────────────────────────────────

  return (
    <div className="h-screen flex flex-row overflow-hidden">
      {/* ── Desktop sidebar — hidden on mobile ──────────────────────── */}
      <div
        className={`hidden md:flex flex-col border-r bg-background transition-all duration-200 ${
          sidebarCollapsed ? 'w-0 overflow-hidden border-r-0' : 'w-72'
        }`}
      >
        <ConversationSidebar
          documentId={documentId!}
          activeConversationId={conversationId ?? null}
          onSelect={handleDesktopSelect}
        />
      </div>

      {/* ── Sidebar toggle button (desktop) ─────────────────────────── */}
      <button
        type="button"
        onClick={() => setSidebarCollapsed((prev) => !prev)}
        className="hidden md:flex items-center justify-center w-5 shrink-0 border-r bg-muted/30 hover:bg-muted/60 transition-colors cursor-pointer"
        aria-label={sidebarCollapsed ? 'Expand sidebar' : 'Collapse sidebar'}
        title={sidebarCollapsed ? 'Expand sidebar' : 'Collapse sidebar'}
      >
        {sidebarCollapsed ? (
          <PanelLeft className="h-3.5 w-3.5 text-muted-foreground" />
        ) : (
          <PanelLeftClose className="h-3.5 w-3.5 text-muted-foreground" />
        )}
      </button>

      {/* ── Mobile drawer overlay ───────────────────────────────────── */}
      {sidebarOpen && (
        <div className="fixed inset-0 z-40 md:hidden">
          {/* Backdrop */}
          <div
            className="fixed inset-0 bg-black/50"
            onClick={() => setSidebarOpen(false)}
          />
          {/* Drawer panel */}
          <div className="fixed inset-y-0 left-0 z-50 w-72 bg-background shadow-xl">
            <ConversationSidebar
              documentId={documentId!}
              activeConversationId={conversationId ?? null}
              onSelect={handleSidebarSelect}
            />
          </div>
        </div>
      )}

      {/* ── Chat area ───────────────────────────────────────────────── */}
      <div className="flex-1 flex flex-col relative min-w-0">
        {/* ── Desktop header ────────────────────────────────────────── */}
        <div className="hidden md:flex items-center gap-3 border-b px-4 py-3 shrink-0">
          <Button
            variant="ghost"
            size="sm"
            onClick={() => navigate(`/documents/${documentId}`)}
            aria-label="Back to document"
          >
            <ArrowLeft className="h-4 w-4" />
          </Button>
          <div className="flex items-center gap-2 min-w-0">
            <MessageSquare className="h-4 w-4 text-muted-foreground shrink-0" />
            <span className="text-sm font-medium truncate">
              {documentTitle ?? 'Document Chat'}
            </span>
          </div>
        </div>

        {/* ── Mobile header ─────────────────────────────────────────── */}
        <div className="md:hidden flex items-center gap-2 border-b px-4 py-3 shrink-0">
          <Button
            variant="ghost"
            size="sm"
            onClick={() => navigate(`/documents/${documentId}`)}
            aria-label="Back to document"
          >
            <ArrowLeft className="h-4 w-4" />
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={() => setSidebarOpen(true)}
            className="gap-2"
          >
            <MessageSquare className="h-4 w-4" />
            Chats
          </Button>
          <div className="flex-1 min-w-0">
            <span className="text-sm font-medium truncate block">
              {documentTitle ?? 'Document Chat'}
            </span>
          </div>
        </div>

        {/* Chat content */}
        {conversationId ? (
          <ChatErrorBoundary>
            <ChatWindow conversationId={conversationId} />
          </ChatErrorBoundary>
        ) : (
          <NoConversationSelected documentId={documentId!} />
        )}
      </div>
    </div>
  );
}
