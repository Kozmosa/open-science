import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useState, type ReactNode } from 'react';
import { getProjects, getCollaborators, addCollaborator, removeCollaborator, getAdminUsers } from '@/shared/api';
import { useAuth } from '@features/auth';
import { useT } from '@/shared/i18n';
import { NativeSelect } from '@design-system/primitives';
import { AccessGrantPanel } from '../../components/settings/AccessGrantPanel';
import { AccessItemRow } from '../../components/settings/AccessItemRow';
import { queryKeys } from '@/shared/api/queryKeys';

export function CollaboratorsTab() {
  const t = useT();
  const { user } = useAuth();
  const queryClient = useQueryClient();
  const [selectedProject, setSelectedProject] = useState<string | null>(null);
  const [addUserId, setAddUserId] = useState('');
  const [addRole, setAddRole] = useState('member');

  const { data: projects } = useQuery({
    queryKey: queryKeys.projects.all,
    queryFn: () => getProjects(),
  });
  const { data: allUsers } = useQuery({
    queryKey: queryKeys.admin.users,
    queryFn: getAdminUsers,
    enabled: user?.role === 'admin',
  });
  const {
    data: collabs,
    isLoading: collabsLoading,
    isError: collabsError,
  } = useQuery({
    queryKey: queryKeys.collaborators.byProject(selectedProject),
    queryFn: () => getCollaborators(selectedProject!),
    enabled: !!selectedProject,
  });

  const addMutation = useMutation({
    mutationFn: () => addCollaborator(selectedProject!, { user_id: addUserId, role: addRole }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.collaborators.byProject(selectedProject) });
      setAddUserId('');
    },
  });

  const removeMutation = useMutation({
    mutationFn: (userId: string) => removeCollaborator(selectedProject!, userId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: queryKeys.collaborators.byProject(selectedProject) }),
  });

  const projectList = projects?.items ?? [];
  const collaboratorList = collabs?.items ?? [];

  const renderRoleBadge = (role: string): ReactNode => {
    const roleLabel = role === 'member'
      ? t('pages.settings.collaborators.role.member')
      : role === 'viewer'
        ? t('pages.settings.collaborators.role.viewer')
        : role; // fallback: display raw role value for unknown roles
    const isMember = role === 'member';
    return (
      <span
        className={`text-xs px-2 py-0.5 rounded-full ${
          isMember
            ? 'bg-[var(--apple-blue)]/10 text-[var(--apple-blue)]'
            : 'bg-[var(--text-secondary)]/10 text-[var(--text-secondary)]'
        }`}
      >
        {roleLabel}
      </span>
    );
  };

  return (
    <div className="flex flex-col gap-4">
      <h3 className="text-sm font-semibold text-[var(--text)]">
        {t('pages.settings.tabs.collaborators')}
      </h3>

      <NativeSelect
        value={selectedProject ?? ''}
        onChange={(e) => setSelectedProject(e.target.value || null)}
      >
        <option value="">{t('pages.settings.collaborators.selectProject')}</option>
        {projectList.map((p) => (
          <option key={p.project_id} value={p.project_id}>
            {p.name}
          </option>
        ))}
      </NativeSelect>

      {!selectedProject && (
        <p className="text-xs text-[var(--text-secondary)]">
          {t('pages.settings.collaborators.noProjectSelected')}
        </p>
      )}

      {selectedProject && (
        <div className="flex flex-col gap-2">
          {collabsLoading && (
            <p className="text-xs text-[var(--text-secondary)]">{t('common.loading')}</p>
          )}
          {collabsError && (
            <p className="text-xs text-red-500">{t('pages.settings.collaborators.loadError')}</p>
          )}
          {!collabsLoading && !collabsError && collaboratorList.length === 0 && (
            <p className="text-xs text-[var(--text-secondary)]">
              {t('pages.settings.collaborators.noCollaborators')}
            </p>
          )}
          {!collabsLoading &&
            !collabsError &&
            collaboratorList.map((c) => (
              <AccessItemRow
                key={c.user_id}
                label={c.username}
                sublabel={c.display_name}
                meta={renderRoleBadge(c.role)}
                onRemove={() => removeMutation.mutate(c.user_id)}
                removeLabel={t('pages.settings.collaborators.remove')}
                disabled={removeMutation.isPending}
              />
            ))}
          <AccessGrantPanel
            users={allUsers?.items ?? []}
            selectedUserId={addUserId}
            onUserChange={setAddUserId}
            onGrant={() => addMutation.mutate()}
            grantLabel={t('pages.settings.collaborators.add')}
            userPlaceholder={t('pages.settings.collaborators.addUser')}
            disabled={addMutation.isPending}
            extraField={
              <select
                value={addRole}
                onChange={(e) => setAddRole(e.target.value)}
                className="text-xs px-2 py-1.5 rounded bg-[var(--surface)] border border-[var(--border)] text-[var(--text)]"
              >
                <option value="member">
                  {t('pages.settings.collaborators.role.member')}
                </option>
                <option value="viewer">
                  {t('pages.settings.collaborators.role.viewer')}
                </option>
              </select>
            }
          />
        </div>
      )}
    </div>
  );
}
