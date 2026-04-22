import { create } from "zustand";
import type { ChatMessage, ChatSession } from "@/lib/types";

interface ChatState {
  // 当前会话
  sessions: ChatSession[];
  currentSessionId: string | null;

  // 当前会话消息
  messages: ChatMessage[];

  // 发送状态
  isLoading: boolean;

  // Actions
  setSessions: (sessions: ChatSession[]) => void;
  addSession: (session: ChatSession) => void;
  removeSession: (sessionId: string) => void;
  setCurrentSessionId: (id: string | null) => void;

  setMessages: (messages: ChatMessage[]) => void;
  addMessage: (message: ChatMessage) => void;
  setIsLoading: (loading: boolean) => void;

  reset: () => void;
}

const initialState = {
  sessions: [],
  currentSessionId: null,
  messages: [],
  isLoading: false,
};

export const useChatStore = create<ChatState>((set) => ({
  ...initialState,

  setSessions: (sessions) => set({ sessions }),

  addSession: (session) =>
    set((state) => ({
      sessions: [session, ...state.sessions],
    })),

  removeSession: (sessionId) =>
    set((state) => ({
      sessions: state.sessions.filter((s) => s.id !== sessionId),
      currentSessionId:
        state.currentSessionId === sessionId ? null : state.currentSessionId,
      messages: state.currentSessionId === sessionId ? [] : state.messages,
    })),

  setCurrentSessionId: (id) => set({ currentSessionId: id }),

  setMessages: (messages) => set({ messages }),

  addMessage: (message) =>
    set((state) => ({
      messages: [...state.messages, message],
    })),

  setIsLoading: (loading) => set({ isLoading: loading }),

  reset: () => set(initialState),
}));
