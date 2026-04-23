import { useQuery } from '@tanstack/react-query';
import { getHealth } from '../api';
import {
  CodeServerCard,
  EnvironmentSelectorPanel,
  HealthStatusBar,
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
      <section className="space-y-3">
        <p className="text-xs font-semibold uppercase tracking-[0.12em] text-[var(--apple-blue)]">
          {t('pages.dashboard.eyebrow')}
        </p>
        <h1
          className="text-[28px] font-normal leading-tight tracking-[0.196px] text-[var(--text)]"
          style={{ fontFamily: 'var(--font-display)' }}
        >
          {t('pages.dashboard.title')}
        </h1>
        <p className="max-w-3xl text-base leading-relaxed tracking-[-0.374px] text-[var(--text-secondary)]">
          {t('pages.dashboard.description')}
        </p>
      </section>

      <section className="space-y-5 rounded-xl bg-[var(--surface)] p-6 shadow-sm">
        <div className="space-y-1">
          <h2
            className="text-lg font-semibold leading-tight tracking-[0.231px] text-[var(--text)]"
            style={{ fontFamily: 'var(--font-display)' }}
          >
            {t('pages.dashboard.surfaceTitle')}
          </h2>
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
        <CodeServerCard selectedEnvironment={environmentSelection.selectedEnvironment} />
      </section>
    </div>
  );
}

export default DashboardPage;
