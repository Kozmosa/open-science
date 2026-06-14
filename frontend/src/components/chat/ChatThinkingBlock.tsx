import { useState } from 'react';
import { ChevronRight } from 'lucide-react';
import { useT } from '../../i18n';

interface ChatThinkingBlockProps {
  content?: string;
}

export default function ChatThinkingBlock({ content }: ChatThinkingBlockProps) {
  const t = useT();
  const [isExpanded, setIsExpanded] = useState(false);

  return (
    <div className="border-l-2 border-[var(--border)] pl-4 py-1 flex flex-col gap-2 transition-colors">
      <button
        type="button"
        className="flex items-center gap-2 cursor-pointer select-none w-fit"
        onClick={() => setIsExpanded(!isExpanded)}
        aria-expanded={isExpanded}
      >
        <ChevronRight
          className={`w-3 h-3 text-[var(--text-tertiary)] transition-transform ${isExpanded ? 'rotate-90' : ''}`}
        />
        <span className="text-xs font-medium text-[var(--text-secondary)] uppercase tracking-widest hover:text-[var(--text)] transition-colors">
          {t('chat.thinking')}
        </span>
      </button>
      {isExpanded && content && (
        <div className="text-sm text-[var(--text-secondary)] italic leading-snug whitespace-pre-wrap animate-in fade-in duration-200">
          {content}
        </div>
      )}
    </div>
  );
}
