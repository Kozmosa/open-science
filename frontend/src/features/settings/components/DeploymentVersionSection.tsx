import { SectionCard, SectionHeader } from '@design-system';
import { useT } from '@/shared/i18n';
import { useQuery } from '@tanstack/react-query';
import { getDeploymentVersion, getFrontendBuildVersion } from '@/shared/api';
import { queryKeys } from '@/shared/api/queryKeys';

export function VersionSideCard({
  side,
  label,
  commit,
  committedAt,
  commitLabel,
  committedAtLabel,
}: {
  side: 'backend' | 'frontend';
  label: string;
  commit: string;
  committedAt: string;
  commitLabel: string;
  committedAtLabel: string;
}) {
  return (
    <div className="rounded-lg border border-[var(--border)] bg-[var(--surface)] px-4 py-3">
      <p className="text-xs font-semibold uppercase tracking-wide text-[var(--text-secondary)]">
        {label}
      </p>
      <div className="mt-2 space-y-2">
        <div>
          <p className="text-[11px] uppercase tracking-wide text-[var(--text-secondary)]">
            {commitLabel}
          </p>
          <p
            className="font-mono text-sm font-medium text-[var(--text)]"
            data-testid={`deployment-version-${side}-commit`}
          >
            {commit}
          </p>
        </div>
        <div>
          <p className="text-[11px] uppercase tracking-wide text-[var(--text-secondary)]">
            {committedAtLabel}
          </p>
          <p
            className="font-mono text-sm font-medium text-[var(--text)]"
            data-testid={`deployment-version-${side}-committed-at`}
          >
            {committedAt}
          </p>
        </div>
      </div>
    </div>
  );
}

export function DeploymentVersionSection() {
  const t = useT();
  const unavailable = t('pages.settings.version.unavailable');
  const commitLabel = t('pages.settings.version.commitLabel');
  const committedAtLabel = t('pages.settings.version.committedAtLabel');
  const { data: backend } = useQuery({
    queryKey: queryKeys.deploymentVersion.backend,
    queryFn: getDeploymentVersion,
  });
  const { data: frontend } = useQuery({
    queryKey: queryKeys.deploymentVersion.frontend,
    queryFn: getFrontendBuildVersion,
  });
  const backendCommit = backend?.short_commit ?? unavailable;
  const backendCommittedAt = backend?.committed_at ?? unavailable;
  const frontendCommit = frontend?.short_commit ?? unavailable;
  const frontendCommittedAt = frontend?.committed_at ?? unavailable;
  const mismatched =
    !!backend?.short_commit &&
    !!frontend?.short_commit &&
    backend.short_commit !== frontend.short_commit;

  return (
    <SectionCard
      header={
        <SectionHeader
          title={t('pages.settings.version.title')}
          description={t('pages.settings.version.description')}
        />
      }
    >
      <div className="space-y-3">
        {mismatched && (
          <p
            className="rounded-lg border border-amber-400/40 bg-amber-400/10 px-4 py-2 text-sm text-amber-600 dark:text-amber-400"
            data-testid="deployment-version-mismatch"
            role="alert"
          >
            {t('pages.settings.version.mismatchWarning')}
          </p>
        )}
        <div className="grid gap-3 rounded-lg bg-[var(--bg-secondary)] p-4 sm:grid-cols-2">
          <VersionSideCard
            side="backend"
            label={t('pages.settings.version.backendLabel')}
            commit={backendCommit}
            committedAt={backendCommittedAt}
            commitLabel={commitLabel}
            committedAtLabel={committedAtLabel}
          />
          <VersionSideCard
            side="frontend"
            label={t('pages.settings.version.frontendLabel')}
            commit={frontendCommit}
            committedAt={frontendCommittedAt}
            commitLabel={commitLabel}
            committedAtLabel={committedAtLabel}
          />
        </div>
      </div>
    </SectionCard>
  );
}

