import { useState, type ReactNode } from 'react';
import { ChevronDown, ChevronRight } from 'lucide-react';
import { useT } from '@/shared/i18n';
import { cn } from '@/shared/utils/cn';
import { Card, CardBody, CardHeader } from './Card';

interface Props {
  children: ReactNode;
  className?: string;
  collapsible?: boolean;
  defaultExpanded?: boolean;
  expanded?: boolean;
  onToggle?: () => void;
  header?: ReactNode;
}

function SectionCard({
  children,
  className = '',
  collapsible = false,
  defaultExpanded = !collapsible,
  expanded: controlledExpanded,
  onToggle,
  header,
}: Props) {
  const [internalExpanded, setInternalExpanded] = useState(defaultExpanded);
  const isControlled = controlledExpanded !== undefined;
  const expanded = isControlled ? controlledExpanded : internalExpanded;
  const t = useT();
  const toggle = () => {
    if (isControlled) {
      onToggle?.();
    } else {
      setInternalExpanded((c) => !c);
    }
  };

  const content = collapsible ? (
    <div
      className={cn(
        'grid transition-[grid-template-rows] duration-200 ease-out',
        expanded ? 'grid-rows-[1fr]' : 'grid-rows-[0fr]'
      )}
    >
      <div className="overflow-hidden">
        <div className="space-y-5 pt-5">{children}</div>
      </div>
    </div>
  ) : (
    <div className="space-y-5">{children}</div>
  );

  return (
    <Card className={cn('p-6', className)}>
      {header ? (
        <CardHeader
          className={cn(
            'flex items-start justify-between gap-3 p-0',
            collapsible && 'cursor-pointer select-none'
          )}
          onClick={collapsible ? toggle : undefined}
        >
          <div className="flex-1">{header}</div>
          {collapsible ? (
            <button
              type="button"
              onClick={(e) => { e.stopPropagation(); toggle(); }}
              className="mt-0.5 shrink-0 rounded p-1 text-[var(--text-tertiary)] transition hover:bg-[var(--bg-secondary)] hover:text-[var(--text)]"
              aria-label={expanded ? t('common.collapse') : t('common.expand')}
            >
              {expanded ? (
                <ChevronDown className="h-4 w-4" />
              ) : (
                <ChevronRight className="h-4 w-4" />
              )}
            </button>
          ) : null}
        </CardHeader>
      ) : null}
      <CardBody className="p-0">{content}</CardBody>
    </Card>
  );
}

export default SectionCard;
