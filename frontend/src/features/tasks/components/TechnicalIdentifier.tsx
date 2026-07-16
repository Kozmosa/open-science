import { Copy } from 'lucide-react';
import { Button } from '@design-system';
import { useT } from '@/shared/i18n';
import { copyText } from '@/shared/utils/clipboard';
import { shortIdentifier } from '../utils/metadataPresentation';

interface TechnicalIdentifierProps {
  label: string;
  value: string | null | undefined;
  fallback?: string;
}

export function TechnicalIdentifier({
  label,
  value,
  fallback = '—',
}: TechnicalIdentifierProps) {
  const t = useT();
  if (!value) {
    return (
      <div className="flex items-center justify-between gap-3 py-1.5">
        <dt className="text-[var(--osci-color-text-muted)]">{label}</dt>
        <dd>{fallback}</dd>
      </div>
    );
  }
  return (
    <div className="flex items-center justify-between gap-3 py-1.5">
      <dt className="text-[var(--osci-color-text-muted)]">{label}</dt>
      <dd className="flex min-w-0 items-center gap-1">
        <code className="truncate" title={value}>{shortIdentifier(value)}</code>
        <Button
          type="button"
          size="icon-sm"
          variant="ghost"
          aria-label={`${t('chat.copy')} ${label}`}
          onClick={() => { void copyText(value); }}
        >
          <Copy aria-hidden="true" size={14} />
        </Button>
      </dd>
    </div>
  );
}
