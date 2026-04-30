import { useQuery } from '@tanstack/react-query';
import { getHealth } from '../api';
import {
  EnvironmentSelectorPanel,
  HealthStatusBar,
  PageHeader,
  SectionCard,
  SectionHeader,
  TerminalBenchCard,
  useEnvironmentSelection,
} from '../components';
import { useT } from '../i18n';

function DashboardPage() {
  const t = useT();
  const healthQuery = useQuery({ queryKey: ['health'], queryFn: getHealth });
  const environmentSelection = useEnvironmentSelection();

  return (
    <div className="space-y-8">
      <PageHeader
        eyebrow={t('pages.dashboard.eyebrow')}
        title={t('pages.dashboard.title')}
        description={t('pages.dashboard.description')}
      />

      <SectionCard>
        <div className="space-y-1">
          <SectionHeader title={t('pages.dashboard.surfaceTitle')} />
          <p className="text-sm leading-relaxed tracking-[-0.224px] text-[var(--text-secondary)]">
            {t('pages.dashboard.endpointsLabel')}{' '}
            <code className="rounded bg-[var(--bg-tertiary)] px-1.5 py-0.5 text-xs">/health</code>,{' '}
            <code className="rounded bg-[var(--bg-tertiary)] px-1.5 py-0.5 text-xs">/v1/health</code>,{' '}
            <code className="rounded bg-[var(--bg-tertiary)] px-1.5 py-0.5 text-xs">/environments</code>,{' '}
            <code className="rounded bg-[var(--bg-tertiary)] px-1.5 py-0.5 text-xs">/v1/environments</code>,{' '}
            <code className="rounded bg-[var(--bg-tertiary)] px-1.5 py-0.5 text-xs">/projects/default/environment-refs</code>,{' '}
            <code className="rounded bg-[var(--bg-tertiary)] px-1.5 py-0.5 text-xs">/v1/projects/default/environment-refs</code>,{' '}
            <code className="rounded bg-[var(--bg-tertiary)] px-1.5 py-0.5 text-xs">/terminal/session</code>,{' '}
            <code className="rounded bg-[var(--bg-tertiary)] px-1.5 py-0.5 text-xs">/terminal/session/reset</code>,{' '}
            <code className="rounded bg-[var(--bg-tertiary)] px-1.5 py-0.5 text-xs">/v1/terminal/session</code>,{' '}
            <code className="rounded bg-[var(--bg-tertiary)] px-1.5 py-0.5 text-xs">/v1/terminal/session/reset</code>,{' '}
            <code className="rounded bg-[var(--bg-tertiary)] px-1.5 py-0.5 text-xs">/code/status</code>,{' '}
            <code className="rounded bg-[var(--bg-tertiary)] px-1.5 py-0.5 text-xs">/code/session</code>,{' '}
            <code className="rounded bg-[var(--bg-tertiary)] px-1.5 py-0.5 text-xs">/v1/code/status</code>, and{' '}
            <code className="rounded bg-[var(--bg-tertiary)] px-1.5 py-0.5 text-xs">/v1/code/session</code>.
          </p>
          <p className="text-sm leading-relaxed tracking-[-0.224px] text-[var(--text-secondary)]">
            {t('pages.dashboard.stateRootLabel')}{' '}
            <code className="rounded bg-[var(--bg-tertiary)] px-1.5 py-0.5 text-xs">
              {healthQuery.data?.state_root ?? '.ainrf'}
            </code>
          </p>
          {healthQuery.data?.detail ? (
            <p className="text-sm text-[#ff9500]">
              {t('pages.dashboard.detailLabel')} {healthQuery.data.detail}
            </p>
          ) : null}
        </div>
        <HealthStatusBar health={healthQuery.data} isLoading={healthQuery.isLoading} />
        <EnvironmentSelectorPanel {...environmentSelection} />
        <TerminalBenchCard selectedEnvironment={environmentSelection.selectedEnvironment} />
      </SectionCard>
    </div>
  );
}

export default DashboardPage;
