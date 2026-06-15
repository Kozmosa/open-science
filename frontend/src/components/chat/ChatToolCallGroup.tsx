import { useState } from 'react';
import { ChevronRight } from 'lucide-react';
import { motion, AnimatePresence } from 'motion/react';
import { useT } from '@/shared/i18n';
import ChatToolCallBlock from './ChatToolCallBlock';
import type { ChatToolCallData } from './types';

interface ChatToolCallGroupProps {
  calls: ChatToolCallData[];
}

export default function ChatToolCallGroup({ calls }: ChatToolCallGroupProps) {
  const t = useT();
  const [isGroupExpanded, setIsGroupExpanded] = useState(false);

  if (calls.length === 1) {
    return <ChatToolCallBlock call={calls[0]} />;
  }

  const overallStatus = calls.some((c) => c.status === 'running') ? 'running' : 'success';

  return (
    <motion.div layout className="w-full relative my-1.5 flex flex-col justify-start">
      <div className="relative w-full">
        {calls.map((call, index) => {
          const isTop = index === 0;
          return (
            <motion.div
              layout
              key={call.id}
              initial={false}
              animate={{
                y: isGroupExpanded ? 0 : index * 5,
                scale: isGroupExpanded ? 1 : Math.max(1 - index * 0.025, 0.9),
                opacity: isGroupExpanded ? 1 : index > 2 ? 0 : 1 - index * 0.1,
              }}
              transition={{ duration: 0.3, type: 'spring', bounce: 0, stiffness: 400, damping: 30 }}
              style={{
                position: isGroupExpanded ? 'relative' : isTop ? 'relative' : 'absolute',
                top: isGroupExpanded ? 'auto' : 0,
                transformOrigin: 'top center',
                zIndex: calls.length - index,
                marginTop: isGroupExpanded && index > 0 ? 4 : 0,
                width: '100%',
              }}
            >
              <ChatToolCallBlock
                call={call}
                forceCollapse={!isGroupExpanded}
                isSummary={!isGroupExpanded && isTop}
                totalCalls={calls.length}
                summaryStatus={overallStatus}
                onExpand={isTop ? () => setIsGroupExpanded(true) : undefined}
              />
            </motion.div>
          );
        })}
      </div>

      <AnimatePresence mode="popLayout" initial={false}>
        {isGroupExpanded && (
          <motion.div
            layout
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: 'auto' }}
            exit={{ opacity: 0, height: 0 }}
            className="flex items-center gap-2 cursor-pointer select-none w-fit mt-1.5 hover:opacity-70 transition-opacity ml-1 overflow-hidden"
            onClick={() => setIsGroupExpanded(false)}
          >
            <ChevronRight className="w-3 h-3 text-[var(--text-tertiary)] -rotate-90" />
            <span className="text-[10.5px] font-semibold text-[var(--text-tertiary)] uppercase tracking-wider">
              {t('chat.collapseTools')}
            </span>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  );
}
