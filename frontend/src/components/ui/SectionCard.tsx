import { useState, type ReactNode } from 'react';
import { ChevronDown, ChevronRight } from 'lucide-react';

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
  defaultExpanded = true,
  expanded: controlledExpanded,
  onToggle,
  header,
}: Props) {
  const [internalExpanded, setInternalExpanded] = useState(defaultExpanded);
  const isControlled = controlledExpanded !== undefined;
  const expanded = isControlled ? controlledExpanded : internalExpanded;
  const toggle = () => {
    if (isControlled) {
      onToggle?.();
    } else {
      setInternalExpanded((c) => !c);
    }
  };

  const content = collapsible ? (
    <div
      className={[
        'grid transition-[grid-template-rows] duration-200 ease-out',
        expanded ? 'grid-rows-[1fr]' : 'grid-rows-[0fr]',
      ].join(' ')}
    >
      <div className="overflow-hidden">
        <div className="space-y-5 pt-5">{children}</div>
      </div>
    </div>
  ) : (
    <div className="space-y-5">{children}</div>
  );

  return (
    <section
      className={['rounded-xl bg-[var(--surface)] p-6 shadow-sm', className].join(' ')}
    >
      {header ? (
        <div className="flex items-start justify-between gap-3">
          <div className="flex-1">{header}</div>
          {collapsible ? (
            <button
              type="button"
              onClick={toggle}
              className="mt-0.5 shrink-0 rounded p-1 text-[var(--text-tertiary)] transition hover:bg-[var(--bg-secondary)] hover:text-[var(--text)]"
              aria-label={expanded ? 'Collapse section' : 'Expand section'}
            >
              {expanded ? (
                <ChevronDown className="h-4 w-4" />
              ) : (
                <ChevronRight className="h-4 w-4" />
              )}
            </button>
          ) : null}
        </div>
      ) : null}
      {content}
    </section>
  );
}

export default SectionCard;
