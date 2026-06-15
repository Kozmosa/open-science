import type { ChatUserMessage as ChatUserMessageType } from './types';

interface ChatUserMessageProps {
  message: ChatUserMessageType;
}

export default function ChatUserMessage({ message }: ChatUserMessageProps) {
  return (
    <div className="flex flex-col items-end">
      <div className="max-w-[85%] sm:max-w-[70%] bg-[var(--color-msg-user-fade)] border border-[var(--prism-primary-border)]/30 rounded-[24px] px-5 py-3 text-sm leading-relaxed text-[var(--text)] whitespace-pre-wrap break-words transition-colors">
        {message.content}
      </div>
    </div>
  );
}
