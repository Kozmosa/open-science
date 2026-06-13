import { memo } from 'react';
import { AssistantBubble } from './AssistantBubble';
import { SystemEventBlock } from './SystemEventBlock';
import { ThinkingBlock } from './ThinkingBlock';
import { ToolCallBlock } from './ToolCallBlock';
import { ToolResultBlock } from './ToolResultBlock';
import { UserBubble } from './UserBubble';
import type { MessageItem } from '../../types';

interface MessageBubbleProps {
  message: MessageItem;
}

export const MessageBubble = memo(function MessageBubble({ message }: MessageBubbleProps) {
  switch (message.type) {
    case 'user':
      return <UserBubble message={message} />;
    case 'assistant':
      return <AssistantBubble message={message} />;
    case 'thinking':
      return <ThinkingBlock message={message} />;
    case 'tool_call':
      return <ToolCallBlock message={message} />;
    case 'tool_result':
      return <ToolResultBlock message={message} />;
    case 'system_event':
      return <SystemEventBlock message={message} />;
    default:
      return <AssistantBubble message={message} />;
  }
});

export default MessageBubble;
