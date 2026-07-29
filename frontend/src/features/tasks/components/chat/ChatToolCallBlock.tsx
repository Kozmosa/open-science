import { useState } from 'react';
import { ChevronRight, CheckCircle2, Loader2, Settings2 } from 'lucide-react';
import { motion, AnimatePresence } from 'motion/react';
import type { ChatToolCallData } from './types';

interface ChatToolCallBlockProps {
  call: ChatToolCallData;
  forceCollapse?: boolean;
  isSummary?: boolean;
  totalCalls?: number;
  summaryStatus?: 'running' | 'success' | 'error';
  onExpand?: () => void;
}

export default function ChatToolCallBlock({
  call,
  forceCollapse = false,
  isSummary = false,
  totalCalls,
  summaryStatus,
  onExpand,
}: ChatToolCallBlockProps) {
  const [internalExpanded, setInternalExpanded] = useState(false);
  const isExpanded = forceCollapse ? false : internalExpanded;

  const statusIcon = (status: 'running' | 'success' | 'error') => {
    switch (status) {
      case 'success':
        return <CheckCircle2 className="w-3.5 h-3.5 text-[var(--color-msg-tool-result)]" />;
      case 'error':
        return <CheckCircle2 className="w-3.5 h-3.5 text-[var(--danger)]" />;
      case 'running':
      default:
        return <Loader2 className="w-3.5 h-3.5 text-[var(--color-msg-tool-call)] animate-spin" />;
    }
  };

  const displayStatus = isSummary ? summaryStatus : call.status;

  return (
    <motion.div layout className="w-full max-w-full">
      <motion.div
        layout
        className="relative overflow-hidden rounded-[14px] bg-[var(--prism-glass)] backdrop-blur-xl border border-[var(--border)] shadow-[var(--shadow-sm)] transition-colors duration-300"
      >
        <motion.button
          type="button"
          layout="position"
          className="flex w-full items-center justify-between px-3 py-2.5 cursor-pointer select-none hover:bg-[var(--color-msg-tool-call-fade)] transition-colors bg-transparent border-none"
          onClick={() => {
            if (onExpand) {
              onExpand();
            }
            if (!forceCollapse) {
              setInternalExpanded(!internalExpanded);
            }
          }}
          aria-label={isSummary ? `${totalCalls} tools called` : call.name}
          aria-expanded={isExpanded}
        >
          <div className="flex items-center gap-2.5 min-w-0">
            <div className="w-6 h-6 rounded-full bg-[var(--color-msg-tool-call-fade)] flex items-center justify-center shadow-[var(--shadow-sm)] border border-[var(--prism-primary-border)]/30">
              <Settings2 className="w-3.5 h-3.5 text-[var(--color-msg-tool-call)]" />
            </div>
            <span className="font-mono text-[12.5px] font-medium text-[var(--text)] tracking-tight truncate">
              {isSummary ? `${totalCalls ?? call.id} Tools Called` : call.name}
            </span>
          </div>
          <div className="flex items-center gap-1.5 shrink-0">
            {displayStatus && statusIcon(displayStatus)}
            <ChevronRight
              className={`w-3.5 h-3.5 text-[var(--text-tertiary)] transition-transform duration-300 ${isExpanded ? 'rotate-90' : ''}`}
            />
          </div>
        </motion.button>

        <AnimatePresence initial={false}>
          {isExpanded && (
            <motion.div
              initial={{ height: 0, opacity: 0 }}
              animate={{ height: 'auto', opacity: 1 }}
              exit={{ height: 0, opacity: 0 }}
              transition={{ duration: 0.25, type: 'spring', bounce: 0, stiffness: 300, damping: 25 }}
              className="overflow-hidden"
            >
              <div className="px-3 pb-3 pt-1 text-[11.5px] font-mono text-[var(--text-secondary)] space-y-2 border-t border-[var(--border)]/50 mx-3 mt-1 pt-2">
                <div>
                  <div className="text-[var(--text-tertiary)] uppercase tracking-wider text-[9px] mb-1 font-sans font-bold">
                    Arguments
                  </div>
                  <div className="bg-[var(--bg-secondary)]/60 p-2.5 rounded-[10px] border border-[var(--border)]/50 break-all whitespace-pre-wrap">
                    {call.args}
                  </div>
                </div>
                {call.result && (
                  <div>
                    <div className="text-[var(--text-tertiary)] uppercase tracking-wider text-[9px] mb-1 font-sans font-bold">
                      Result
                    </div>
                    <div className="bg-[var(--bg-secondary)]/60 p-2.5 rounded-[10px] border border-[var(--border)]/50 break-all max-h-32 overflow-y-auto whitespace-pre-wrap">
                      {call.result}
                    </div>
                  </div>
                )}
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </motion.div>
    </motion.div>
  );
}
