import { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import {
  ArrowLeft,
  MessageSquare,
  PanelLeftClose,
  PanelLeft,
  Search,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import ConversationSidebar from '@/components/chat/ConversationSidebar';
import ChatWindow from '@/components/chat/ChatWindow';
import ChatErrorBoundary from '@/components/chat/ChatErrorBoundary';
import ModeSelector from '@/components/rag/ModeSelector';
import GlobalRagEmptyState from '@/components/rag/GlobalRagEmptyState';
import { useConversationStore } from '@/stores/conversationStore';

// ── NoConversationSelected Sub-Component ──────────────────────────────────

function NoConversationSelected() {
  const navigate = useNavigate();
  const createConversation = useConversationStore((s) => s.createConversation);

  const handleSend = async (content: string) => {
    try {
      const conv = await createConversation(undefined, content.slice(0, 80));
      navigate(`/legal-research/${conv.id}`, { replace: true });
    } catch {
      // Error handled by store
    }
  };

  return (
    <GlobalRagEmptyState onSend={handleSend} />
  );
}

// ── Main Component ────────────────────────────────────────────────────────

export default function GlobalRagChatPage() {
  const { conversationId } = useParams<{ conversationId?: string }>();
  const navigate = useNavigate();

  // Mobile sidebar drawer state
  const [sidebarOpen, setSidebarOpen] = useState(false);

  // Desktop sidebar collapse state
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);

  // Dynamic page title
  useEffect(() => {
    document.title = 'Legal Research | DocuChat';
    return () => {
      document.title = 'DocuChat';
    };
  }, []);

  // ── Handlers ──────────────────────────────────────────────────────────

  const handleSidebarSelect = (id: string) => {
    navigate(`/legal-research/${id}`);
    setSidebarOpen(false);
  };

  const handleDesktopSelect = (id: string) => {
    navigate(`/legal-research/${id}`);
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
            onClick={() => navigate('/dashboard')}
            aria-label="Back to dashboard"
          >
            <ArrowLeft className="h-4 w-4" />
          </Button>
          <div className="flex items-center gap-2 min-w-0">
            <Search className="h-4 w-4 text-muted-foreground shrink-0" />
            <span className="text-sm font-medium truncate">
              Legal Research
            </span>
          </div>
          <div className="flex-1" />
          <ModeSelector />
        </div>

        {/* ── Mobile header ─────────────────────────────────────────── */}
        <div className="md:hidden flex items-center gap-2 border-b px-4 py-3 shrink-0">
          <Button
            variant="ghost"
            size="sm"
            onClick={() => navigate('/dashboard')}
            aria-label="Back to dashboard"
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
              Legal Research
            </span>
          </div>
        </div>

        {/* Chat content */}
        {conversationId ? (
          <ChatErrorBoundary>
            <ChatWindow conversationId={conversationId} />
          </ChatErrorBoundary>
        ) : (
          <NoConversationSelected />
        )}
      </div>
    </div>
  );
}
