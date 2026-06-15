import { useCallback } from 'react';
import { useQuery } from '@tanstack/react-query';
import { ExternalLink, BarChart3, Activity, Sparkles, Server } from 'lucide-react';
import { getMonitoringSettings } from '@/shared/api';
import { SectionCard, SectionHeader } from '@design-system/primitives';
import { useT } from '@/shared/i18n';
import type { MonitoringServiceItem } from '@/shared/types';
import { queryKeys } from '@/shared/api/queryKeys';

const ICON_MAP: Record<string, React.ComponentType<{ className?: string }>> = {
  grafana: BarChart3,
  prometheus: Activity,
  litefuse: Sparkles,
};

const SERVICE_FALLBACK_ICON = Server;

function ServiceIcon({ icon, className }: { icon: string; className?: string }) {
  const IconComponent = ICON_MAP[icon] ?? SERVICE_FALLBACK_ICON;
  return <IconComponent className={className} />;
}

/** Returns true if the URL is an absolute external URL (has a scheme). */
function isExternalUrl(url: string): boolean {
  return /^https?:\/\//.test(url);
}

function MonitoringCard({ service }: { service: MonitoringServiceItem }) {
  const t = useT();
  const configured = !!service.url;

  const handleNavigate = useCallback(() => {
    if (!service.url) return;
    if (isExternalUrl(service.url)) {
      window.open(service.url, '_blank', 'noopener,noreferrer');
    } else {
      // Relative path — navigate in the same tab so browser back works.
      window.location.href = service.url;
    }
  }, [service.url]);

  return (
    <div
      role={configured ? 'button' : undefined}
      tabIndex={configured ? 0 : undefined}
      onClick={configured ? handleNavigate : undefined}
      onKeyDown={
        configured
          ? (e) => {
              if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                handleNavigate();
              }
            }
          : undefined
      }
      className={`group relative flex flex-col rounded-xl border bg-[var(--surface)] p-5 transition-all duration-200 outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)] ${
        configured
          ? 'border-[var(--border)] shadow-[var(--shadow-card)] hover:shadow-[var(--shadow-pane)] hover:-translate-y-0.5 cursor-pointer'
          : 'border-dashed border-[var(--border)] opacity-60'
      }`}
    >
      {/* Card header with icon */}
      <div className="mb-4 flex items-start justify-between">
        <div
          className={`flex h-10 w-10 items-center justify-center rounded-lg transition-colors ${
            configured
              ? 'bg-[var(--accent)]/10 text-[var(--accent)] group-hover:bg-[var(--accent)]/15'
              : 'bg-[var(--bg-secondary)] text-[var(--text-tertiary)]'
          }`}
        >
          <ServiceIcon icon={service.icon} className="h-5 w-5" />
        </div>
        {configured && (
          <ExternalLink className="h-4 w-4 shrink-0 text-[var(--text-tertiary)] opacity-0 transition-opacity group-hover:opacity-100" />
        )}
      </div>

      {/* Service name & description */}
      <h3 className="mb-1 text-sm font-semibold text-[var(--text)]">
        {service.display_name}
      </h3>
      <p className="mb-4 flex-1 text-xs leading-relaxed text-[var(--text-secondary)]">
        {service.description}
      </p>

      {/* Status / action area */}
      <div className="mt-auto">
        {configured ? (
          <a
            href={service.url!}
            target={isExternalUrl(service.url!) ? '_blank' : undefined}
            rel={isExternalUrl(service.url!) ? 'noopener noreferrer' : undefined}
            className="inline-flex w-full items-center justify-center gap-1.5 rounded-lg bg-[var(--accent)]/10 px-3 py-2 text-xs font-medium text-[var(--accent)] transition-colors hover:bg-[var(--accent)]/20"
            onClick={(e) => e.stopPropagation()}
          >
            <ExternalLink className="h-3.5 w-3.5" />
            {t('pages.settings.monitoring.openService', { name: service.display_name })}
          </a>
        ) : (
          <div className="flex items-center gap-1.5 rounded-lg bg-[var(--bg-secondary)] px-3 py-2 text-xs text-[var(--text-tertiary)]">
            <span className="inline-block h-1.5 w-1.5 rounded-full bg-[var(--text-tertiary)]" />
            {t('pages.settings.monitoring.notConfigured')}
          </div>
        )}
      </div>
    </div>
  );
}

export default function MonitoringTab() {
  const t = useT();
  const { data, isLoading, error } = useQuery({
    queryKey: queryKeys.monitoring.settings,
    queryFn: getMonitoringSettings,
    staleTime: 5 * 60 * 1000, // 5 minutes — these URLs rarely change
  });

  const services = data?.services ?? [];
  const hasAnyConfigured = services.some((s) => !!s.url);

  return (
    <div className="space-y-6">
      <SectionCard
        header={
          <SectionHeader
            title={t('pages.settings.monitoring.title')}
            description={t('pages.settings.monitoring.description')}
          />
        }
      >
        {isLoading ? (
          <p className="text-sm text-[var(--text-tertiary)]">{t('common.loading')}</p>
        ) : error ? (
          <p className="text-sm text-[var(--danger)]">
            {error instanceof Error ? error.message : String(error)}
          </p>
        ) : services.length === 0 ? (
          <div className="rounded-lg border border-dashed border-[var(--border)] bg-[var(--bg-secondary)] p-5 text-sm text-[var(--text-tertiary)]">
            {t('pages.settings.monitoring.noServices')}
          </div>
        ) : (
          <>
            {!hasAnyConfigured && (
              <div className="mb-5 rounded-lg border border-[var(--warning-border)] bg-[var(--warning-soft)] px-4 py-3 text-xs text-[var(--warning-foreground)]">
                {t('pages.settings.monitoring.noServices')}
              </div>
            )}
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {services.map((service) => (
                <MonitoringCard key={service.id} service={service} />
              ))}
            </div>
          </>
        )}
      </SectionCard>
    </div>
  );
}
