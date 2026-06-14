import type { ChatUserMessage as ChatUserMessageType } from './types';

interface ChatUserMessageProps {
  message: ChatUserMessageType;
}

export default function ChatUserMessage({ message }: ChatUserMessageProps) {
  return (
    <div className="flex flex-col items-end">
      <div className="max-w-[85%] sm:max-w-[70%] bg-[var(--bg-secondary)] rounded-[24px] px-5 py-3 text-sm leading-relaxed text-[var(--text)] whitespace-pre-wrap transition-colors">
        {message.content}
      </div>
    </div>
  );
}
