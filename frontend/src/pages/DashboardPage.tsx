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
    <div className="px-4 py-8 sm:px-6 lg:px-8">
      <section className="mb-8 space-y-3">
        <p className="text-sm font-medium uppercase tracking-wide text-[var(--accent)]">
          {t('pages.dashboard.eyebrow')}
        </p>
        <h1 className="text-3xl font-semibold text-gray-900">{t('pages.dashboard.title')}</h1>
        <p className="max-w-3xl text-sm text-gray-600 sm:text-base">
          {t('pages.dashboard.description')}
        </p>
      </section>

      <section className="space-y-4 rounded-2xl border border-gray-200 bg-white p-6 shadow-sm">
        <div className="space-y-1">
          <h2 className="text-lg font-medium text-gray-900">{t('pages.dashboard.surfaceTitle')}</h2>
          <p className="text-sm text-gray-600">
            {t('pages.dashboard.endpointsLabel')} <code className="rounded bg-gray-100 px-1.5 py-0.5">/health</code>,{' '}
            <code className="rounded bg-gray-100 px-1.5 py-0.5">/v1/health</code>,{' '}
            <code className="rounded bg-gray-100 px-1.5 py-0.5">/environments</code>,{' '}
            <code className="rounded bg-gray-100 px-1.5 py-0.5">/v1/environments</code>,{' '}
            <code className="rounded bg-gray-100 px-1.5 py-0.5">/projects/default/environment-refs</code>,{' '}
            <code className="rounded bg-gray-100 px-1.5 py-0.5">/v1/projects/default/environment-refs</code>,{' '}
            <code className="rounded bg-gray-100 px-1.5 py-0.5">/terminal/session</code>,{' '}
            <code className="rounded bg-gray-100 px-1.5 py-0.5">/terminal/session/reset</code>,{' '}
            <code className="rounded bg-gray-100 px-1.5 py-0.5">/v1/terminal/session</code>,{' '}
            <code className="rounded bg-gray-100 px-1.5 py-0.5">/v1/terminal/session/reset</code>,{' '}
            <code className="rounded bg-gray-100 px-1.5 py-0.5">/code/status</code>,{' '}
            <code className="rounded bg-gray-100 px-1.5 py-0.5">/code/session</code>,{' '}
            <code className="rounded bg-gray-100 px-1.5 py-0.5">/v1/code/status</code>, and{' '}
            <code className="rounded bg-gray-100 px-1.5 py-0.5">/v1/code/session</code>.
          </p>
          <p className="text-sm text-gray-600">
            {t('pages.dashboard.stateRootLabel')}{' '}
            <code className="rounded bg-gray-100 px-1.5 py-0.5">{healthQuery.data?.state_root ?? '.ainrf'}</code>
          </p>
          {healthQuery.data?.detail ? (
            <p className="text-sm text-yellow-700">
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
