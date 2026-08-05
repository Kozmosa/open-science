import type { MessageItem } from '../../types';

export type ChatMessageRole = 'user' | 'assistant' | 'system';

export type ToolCallStatus = 'running' | 'success' | 'error';

export interface ChatToolCallData {
  id: string;
  name: string;
  args: string;
  result?: string;
  status: ToolCallStatus;
}

export interface BaseChatMessage {
  id: string;
  sequence: number;
  timestamp: string;
}

export interface ChatUserMessage extends BaseChatMessage {
  role: 'user';
  content: string;
}

export interface ChatSystemMessage extends BaseChatMessage {
  role: 'system';
  content: string;
}

export interface ChatAssistantMessage extends BaseChatMessage {
  role: 'assistant';
  content?: string;
  thinking?: string;
  toolCalls?: ChatToolCallData[];
  isStreaming: boolean;
  aborted: boolean;
}

export type ChatMessage = ChatUserMessage | ChatAssistantMessage | ChatSystemMessage;

export interface AssistantGroupState {
  id: string;
  sequence: number;
  timestamp: string;
  content?: string;
  thinking?: string;
  toolCalls: Map<string, ChatToolCallData>;
  isStreaming: boolean;
}

export interface GroupMessagesOptions {
  /**
   * If true, a completed assistant turn (one that already has content) will
   * start a new group when the next thinking/tool_call arrives. This prevents
   * unrelated assistant bursts from being merged. Defaults to true.
   */
  splitOnContent?: boolean;
}

export type { MessageItem };
