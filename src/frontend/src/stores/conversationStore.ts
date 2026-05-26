import { create } from 'zustand';
import {
  listConversations,
  createConversation as apiCreateConversation,
  getConversation,
  sendMessage as apiSendMessage,
  sendMessageStream as apiSendMessageStream,
  deleteConversation as apiDeleteConversation,
  renameConversation as apiRenameConversation,
} from '@/api/conversations';
import type { Conversation, ConversationDetail, Message, MessageSource, RagMode, TokenUsage } from '@/api/conversations';

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
  isCreatingConversation: boolean;
  streamingContent: string;
  thinkingStatus: string | null;
  thinkingReasoning: string | null;
  error: string | null;
  ragMode: RagMode;
}

interface ConversationActions {
  fetchConversations: (documentId?: string) => Promise<void>;
  createConversation: (documentId?: string, title?: string) => Promise<Conversation>;
  loadConversation: (conversationId: string) => Promise<void>;
  sendMessage: (conversationId: string, content: string, mode?: RagMode) => Promise<void>;
  sendMessageStream: (conversationId: string, content: string, mode?: RagMode) => Promise<void>;
  renameConversation: (conversationId: string, title: string) => Promise<void>;
  deleteConversation: (conversationId: string) => Promise<void>;
  clearActiveConversation: () => void;
  clearError: () => void;
  setRagMode: (mode: RagMode) => void;
}

type ConversationStore = ConversationState & ConversationActions;

// ── Initial State ──────────────────────────────────────────────────────

const initialState: ConversationState = {
  conversations: [],
  activeConversation: null,
  isLoadingConversations: false,
  isLoadingMessages: false,
  isSendingMessage: false,
  isCreatingConversation: false,
  streamingContent: '',
  thinkingStatus: null,
  thinkingReasoning: null,
  error: null,
  ragMode: 'local_rag',
};

// ── Store ──────────────────────────────────────────────────────────────

export const useConversationStore = create<ConversationStore>((set) => ({
  ...initialState,

  fetchConversations: async (documentId?: string): Promise<void> => {
    set({ isLoadingConversations: true, error: null });
    try {
      const data = await listConversations(documentId);
      set({ conversations: data.results, isLoadingConversations: false });
    } catch (error: unknown) {
      const message = error instanceof Error ? error.message : 'Failed to fetch conversations';
      set({ error: message, isLoadingConversations: false });
    }
  },

  createConversation: async (documentId?: string, title?: string): Promise<Conversation> => {
    set({ isCreatingConversation: true, error: null });
    try {
      const newConv = await apiCreateConversation(documentId, title);
      set((state) => ({
        conversations: [newConv, ...state.conversations],
        isCreatingConversation: false,
      }));
      return newConv;
    } catch (error: unknown) {
      set({ isCreatingConversation: false });
      throw error;
    }
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

  sendMessage: async (conversationId: string, content: string, mode?: RagMode): Promise<void> => {
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
      thinkingStatus: 'Processing your request...',
      thinkingReasoning: null,
      error: null,
      activeConversation: state.activeConversation
        ? {
            ...state.activeConversation,
            messages: [...state.activeConversation.messages, optimisticMessage],
          }
        : null,
    }));

    try {
      const assistantMessage = await apiSendMessage(conversationId, content, mode);

      set((state) => ({
        isSendingMessage: false,
        thinkingStatus: null,
        thinkingReasoning: null,
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
        thinkingStatus: null,
        thinkingReasoning: null,
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

  sendMessageStream: async (conversationId: string, content: string, mode?: RagMode): Promise<void> => {
    const tempId = generateTempId();
    const tempAssistantId = 'temp-assistant-' + crypto.randomUUID();

    const optimisticMessage: Message = {
      id: tempId,
      role: 'user',
      content,
      sources: [],
      token_usage: null,
      created_at: new Date().toISOString(),
    };

    const tempAssistantMessage: Message = {
      id: tempAssistantId,
      role: 'assistant',
      content: '',
      sources: [],
      token_usage: null,
      created_at: new Date().toISOString(),
    };

    set((state) => ({
      isSendingMessage: true,
      streamingContent: '',
      thinkingStatus: null,
      thinkingReasoning: null,
      error: null,
      activeConversation: state.activeConversation
        ? {
            ...state.activeConversation,
            messages: [...state.activeConversation.messages, optimisticMessage, tempAssistantMessage],
          }
        : null,
    }));

    return new Promise<void>((resolve, reject) => {
      apiSendMessageStream(
        conversationId,
        content,
        // onToken
        (token: string) => {
          set((state) => {
            const newStreamingContent = state.streamingContent + token;
            return {
              streamingContent: newStreamingContent,
              activeConversation: state.activeConversation
                ? {
                    ...state.activeConversation,
                    messages: state.activeConversation.messages.map((msg) =>
                      msg.id === tempAssistantId
                        ? { ...msg, content: newStreamingContent }
                        : msg,
                    ),
                  }
                : null,
            };
          });
        },
        // onDone
        (data: { message_id: string; sources: MessageSource[]; token_usage: TokenUsage }) => {
          set((state) => ({
            isSendingMessage: false,
            streamingContent: '',
            thinkingStatus: null,
            thinkingReasoning: null,
            activeConversation: state.activeConversation
              ? {
                  ...state.activeConversation,
                  messages: state.activeConversation.messages.map((msg) =>
                    msg.id === tempAssistantId
                      ? {
                          ...msg,
                          id: data.message_id,
                          sources: data.sources,
                          token_usage: data.token_usage,
                        }
                      : msg,
                  ),
                }
              : null,
          }));
          resolve();
        },
        // onError
        (error: Error) => {
          set((state) => ({
            isSendingMessage: false,
            streamingContent: '',
            thinkingStatus: null,
            thinkingReasoning: null,
            error: error.message,
            activeConversation: state.activeConversation
              ? {
                  ...state.activeConversation,
                  messages: state.activeConversation.messages.filter(
                    (m) => m.id !== tempAssistantId && m.id !== tempId,
                  ),
                }
              : null,
          }));
          reject(error);
        },
        mode,
        // onProgress
        (status: string, reasoning?: string) => {
          set({ thinkingStatus: status, thinkingReasoning: reasoning ?? null });
        },
      );
    });
  },

  renameConversation: async (conversationId: string, title: string): Promise<void> => {
    try {
      const updated = await apiRenameConversation(conversationId, title);
      set((state) => ({
        conversations: state.conversations.map((c) =>
          c.id === conversationId ? { ...c, title: updated.title } : c,
        ),
        activeConversation:
          state.activeConversation?.id === conversationId
            ? { ...state.activeConversation, title: updated.title }
            : state.activeConversation,
      }));
    } catch (error: unknown) {
      const message = error instanceof Error ? error.message : 'Failed to rename conversation';
      set({ error: message });
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

  setRagMode: (mode: RagMode): void => {
    set({ ragMode: mode });
  },
}));
