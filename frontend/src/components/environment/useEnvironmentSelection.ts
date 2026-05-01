import { useEffect, useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { getEnvironments, getProjectEnvironmentReferences } from '../../api';
import type { EnvironmentRecord, ProjectEnvironmentReference } from '../../types';
import { useSettings } from '../../settings';

const defaultProjectId = 'default';
const EMPTY_ENVIRONMENTS: EnvironmentRecord[] = [];
const EMPTY_PROJECT_REFERENCES: ProjectEnvironmentReference[] = [];

function resolveEnvironmentSelection(
  sessionEnvironmentId: string | null,
  projectDefaultEnvironmentId: string | null,
  rememberedEnvironmentId: string | null,
  environments: EnvironmentRecord[]
): string | null {
  if (environments.length === 0) {
    return null;
  }

  const sessionEnvironment = sessionEnvironmentId
    ? environments.find((environment) => environment.id === sessionEnvironmentId) ?? null
    : null;
  if (sessionEnvironment !== null) {
    return sessionEnvironment.id;
  }

  const projectDefaultEnvironment = projectDefaultEnvironmentId
    ? environments.find((environment) => environment.id === projectDefaultEnvironmentId) ?? null
    : null;
  if (projectDefaultEnvironment !== null) {
    return projectDefaultEnvironment.id;
  }

  const rememberedEnvironment = rememberedEnvironmentId
    ? environments.find((environment) => environment.id === rememberedEnvironmentId) ?? null
    : null;
  if (rememberedEnvironment !== null) {
    return rememberedEnvironment.id;
  }

  const defaultEnvironment = environments.find((environment) => environment.is_seed);
  if (defaultEnvironment !== undefined) {
    return defaultEnvironment.id;
  }

  return environments[0]?.id ?? null;
}

export interface EnvironmentSelectionState {
  environments: EnvironmentRecord[];
  projectReferences: ProjectEnvironmentReference[];
  projectDefaultEnvironmentId: string | null;
  selectedEnvironmentId: string | null;
  selectedEnvironment: EnvironmentRecord | null;
  isLoading: boolean;
  loadError: string | null;
  hasEnvironments: boolean;
  onSelectEnvironment: (environmentId: string) => void;
}

export function useEnvironmentSelection(): EnvironmentSelectionState {
  const { settings, rememberSelectedEnvironment } = useSettings();
  const environmentsQuery = useQuery({
    queryKey: ['environments'],
    queryFn: getEnvironments,
  });
  const projectReferencesQuery = useQuery({
    queryKey: ['project-environment-refs', defaultProjectId],
    queryFn: () => getProjectEnvironmentReferences(defaultProjectId),
  });
  const [sessionEnvironmentId, setSessionEnvironmentId] = useState<string | null>(null);
  const environments = environmentsQuery.data?.items ?? EMPTY_ENVIRONMENTS;
  const projectReferences = projectReferencesQuery.data?.items ?? EMPTY_PROJECT_REFERENCES;

  const projectSettings = settings.projectDefaults[defaultProjectId];
  const storedEnvironmentId = projectSettings?.selection.lastEnvironmentId ?? null;
  const projectDefaultEnvironmentId = projectSettings?.defaultEnvironmentId ?? null;

  const selectedEnvironmentId = useMemo(
    () =>
      resolveEnvironmentSelection(
        sessionEnvironmentId,
        projectDefaultEnvironmentId,
        storedEnvironmentId,
        environments
      ),
    [
      environments,
      sessionEnvironmentId,
      projectDefaultEnvironmentId,
      storedEnvironmentId,
    ]
  );

  useEffect(() => {
    if (storedEnvironmentId === null || environments.length === 0) {
      return;
    }

    const storedEnvironmentStillExists = environments.some(
      (environment) => environment.id === storedEnvironmentId
    );
    if (storedEnvironmentStillExists) {
      return;
    }

    rememberSelectedEnvironment(defaultProjectId, selectedEnvironmentId);
  }, [environments, rememberSelectedEnvironment, selectedEnvironmentId, storedEnvironmentId]);

  const selectedEnvironment = useMemo(
    () => environments.find((environment) => environment.id === selectedEnvironmentId) ?? null,
    [environments, selectedEnvironmentId]
  );

  const loadError = [environmentsQuery.error, projectReferencesQuery.error]
    .filter((error): error is Error => error instanceof Error)
    .map((error) => error.message)
    .join(' | ') || null;

  const onSelectEnvironment = (environmentId: string): void => {
    setSessionEnvironmentId(environmentId);
    rememberSelectedEnvironment(defaultProjectId, environmentId);
  };

  return {
    environments,
    projectReferences,
    projectDefaultEnvironmentId,
    selectedEnvironmentId,
    selectedEnvironment,
    isLoading: environmentsQuery.isLoading || projectReferencesQuery.isLoading,
    loadError,
    hasEnvironments: environments.length > 0,
    onSelectEnvironment,
  };
}
