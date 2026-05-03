import { create } from 'zustand';
import {
  listConversations,
  createConversation as apiCreateConversation,
  getConversation,
  sendMessage as apiSendMessage,
  deleteConversation as apiDeleteConversation,
} from '@/api/conversations';
import type { Conversation, ConversationDetail, Message } from '@/api/conversations';

// ── Helpers ────────────────────────────────────────────────────────────

/**
 * Generate a temporary ID for optimistic message updates.
 * Uses crypto.randomUUID() if available, falls back to Date.now().
 */
function generateTempId(): string {
  try {
    return 'temp-' + crypto.randomUUID();
  } catch {
    return 'temp-' + Date.now().toString() + '-' + Math.random().toString(36).slice(2, 9);
  }
}

// ── State & Actions Types ──────────────────────────────────────────────

interface ConversationState {
  conversations: Conversation[];
  activeConversation: ConversationDetail | null;
  isLoadingConversations: boolean;
  isLoadingMessages: boolean;
  isSendingMessage: boolean;
  error: string | null;
}

interface ConversationActions {
  fetchConversations: (documentId: string) => Promise<void>;
  createConversation: (documentId: string, title?: string) => Promise<Conversation>;
  loadConversation: (conversationId: string) => Promise<void>;
  sendMessage: (conversationId: string, content: string) => Promise<void>;
  deleteConversation: (conversationId: string) => Promise<void>;
  clearActiveConversation: () => void;
  clearError: () => void;
}

type ConversationStore = ConversationState & ConversationActions;

// ── Initial State ──────────────────────────────────────────────────────

const initialState: ConversationState = {
  conversations: [],
  activeConversation: null,
  isLoadingConversations: false,
  isLoadingMessages: false,
  isSendingMessage: false,
  error: null,
};

// ── Store ──────────────────────────────────────────────────────────────

export const useConversationStore = create<ConversationStore>((set) => ({
  ...initialState,

  fetchConversations: async (documentId: string): Promise<void> => {
    set({ isLoadingConversations: true, error: null });
    try {
      const data = await listConversations(documentId);
      set({ conversations: data.results, isLoadingConversations: false });
    } catch (error: unknown) {
      const message = error instanceof Error ? error.message : 'Failed to fetch conversations';
      set({ error: message, isLoadingConversations: false });
    }
  },

  createConversation: async (documentId: string, title?: string): Promise<Conversation> => {
    const newConv = await apiCreateConversation(documentId, title);
    set((state) => ({
      conversations: [newConv, ...state.conversations],
    }));
    return newConv;
  },

  loadConversation: async (conversationId: string): Promise<void> => {
    set({ isLoadingMessages: true, error: null });
    try {
      const data = await getConversation(conversationId);
      set({ activeConversation: data, isLoadingMessages: false });
    } catch (error: unknown) {
      const message = error instanceof Error ? error.message : 'Failed to load conversation';
      set({ error: message, isLoadingMessages: false });
    }
  },

  sendMessage: async (conversationId: string, content: string): Promise<void> => {
    const tempId = generateTempId();

    const optimisticMessage: Message = {
      id: tempId,
      role: 'user',
      content,
      sources: [],
      token_usage: null,
      created_at: new Date().toISOString(),
    };

    set((state) => ({
      isSendingMessage: true,
      error: null,
      activeConversation: state.activeConversation
        ? {
            ...state.activeConversation,
            messages: [...state.activeConversation.messages, optimisticMessage],
          }
        : null,
    }));

    try {
      const assistantMessage = await apiSendMessage(conversationId, content);

      set((state) => ({
        isSendingMessage: false,
        activeConversation: state.activeConversation
          ? {
              ...state.activeConversation,
              messages: [...state.activeConversation.messages, assistantMessage],
            }
          : null,
      }));
    } catch (error: unknown) {
      const message = error instanceof Error ? error.message : 'Failed to send message';

      set((state) => ({
        isSendingMessage: false,
        error: message,
        activeConversation: state.activeConversation
          ? {
              ...state.activeConversation,
              messages: state.activeConversation.messages.filter((m) => m.id !== tempId),
            }
          : null,
      }));
    }
  },

  deleteConversation: async (conversationId: string): Promise<void> => {
    try {
      await apiDeleteConversation(conversationId);
      set((state) => ({
        conversations: state.conversations.filter((c) => c.id !== conversationId),
        activeConversation:
          state.activeConversation?.id === conversationId ? null : state.activeConversation,
      }));
    } catch (error: unknown) {
      const message = error instanceof Error ? error.message : 'Failed to delete conversation';
      set({ error: message });
    }
  },

  clearActiveConversation: (): void => {
    set({ activeConversation: null });
  },

  clearError: (): void => {
    set({ error: null });
  },
}));
