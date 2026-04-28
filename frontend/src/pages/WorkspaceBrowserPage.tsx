import { useQuery } from '@tanstack/react-query';
import { getHealth } from '../api';
import { CodeServerCard, useEnvironmentSelection } from '../components';
import { useT } from '../i18n';
import type { RuntimeDependencyStatus } from '../types';

function readinessBlockers(
  dependencies: Record<string, RuntimeDependencyStatus> | undefined
): RuntimeDependencyStatus[] {
  if (!dependencies) {
    return [];
  }
  return Object.values(dependencies).filter((dependency) => !dependency.available);
}

function WorkspaceBrowserPage() {
  const t = useT();
  const environmentSelection = useEnvironmentSelection();
  const healthQuery = useQuery({ queryKey: ['health'], queryFn: getHealth });
  const blockers = readinessBlockers(healthQuery.data?.runtime_readiness?.dependencies);

  return (
    <div className="space-y-8">
      <section className="space-y-3">
        <p className="text-xs font-semibold uppercase tracking-[0.12em] text-[var(--apple-blue)]">
          {t('pages.workspaceBrowser.eyebrow')}
        </p>
        <h1
          className="text-[28px] font-normal leading-tight tracking-[0.196px] text-[var(--text)]"
          style={{ fontFamily: 'var(--font-display)' }}
        >
          {t('pages.workspaceBrowser.title')}
        </h1>
        <p className="max-w-3xl text-base leading-relaxed tracking-[-0.374px] text-[var(--text-secondary)]">
          {t('pages.workspaceBrowser.description')}
        </p>
      </section>

      {blockers.length > 0 ? (
        <section className="space-y-2 rounded-xl border border-[#ff9500]/40 bg-[#ff9500]/10 p-4">
          <h2 className="text-sm font-semibold text-[var(--text)]">
            {t('pages.workspaceBrowser.readinessTitle')}
          </h2>
          <ul className="list-disc space-y-1 pl-5 text-sm text-[var(--text-secondary)]">
            {blockers.map((dependency) => (
              <li key={dependency.detail ?? dependency.path ?? 'missing-dependency'}>
                {dependency.detail ?? t('pages.workspaceBrowser.readinessMissingDependency')}
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      <CodeServerCard selectedEnvironment={environmentSelection.selectedEnvironment} />
    </div>
  );
}

export default WorkspaceBrowserPage;
