/**
 * Centralized React Query key factory.
 *
 * Every query key in the application is registered here so that
 * invalidations and cache lookups stay consistent.  Use these
 * factories instead of raw string arrays in useQuery / useMutation
 * calls.
 *
 * Factory methods accept `string | null` for id-like parameters
 * because many callers pass nullable React state / URL params.
 */
export const queryKeys = {
  health: {
    all: ['health'] as const,
  },

  environments: {
    all: ['environments'] as const,
  },

  projects: {
    all: ['projects'] as const,
    detail: (projectId: string | null) => ['project', projectId] as const,
  },

  workspaces: {
    all: ['workspaces'] as const,
  },

  tasks: {
    all: ['tasks'] as const,
    list: (showArchived: boolean, taskSort: string) =>
      ['tasks', showArchived, taskSort] as const,
    archived: (showArchived: true) => ['tasks', showArchived] as const,
    detail: (taskId: string | null) => ['task', taskId] as const,
    messages: (taskId: string | null) => ['task-messages', taskId] as const,
    tokenUsage: (opts: { includeArchived: boolean }) =>
      ['task-token-usage', opts] as const,
  },

  taskEdges: {
    byProject: (projectId: string | null) =>
      ['task-edges', projectId] as const,
  },

  projectTasks: {
    byProject: (projectId: string | null) =>
      ['project-tasks', projectId] as const,
  },

  projectEnvironmentRefs: {
    byProject: (projectId: string) =>
      ['project-environment-refs', projectId] as const,
  },

  skills: {
    all: ['skills'] as const,
    detail: (skillId: string | null) => ['skillDetail', skillId] as const,
    preview: (skillId: string | null) => ['skillPreview', skillId] as const,
    registries: ['skillRegistries'] as const,
  },

  search: {
    settings: ['searchSettings'] as const,
  },

  monitoring: {
    settings: ['monitoringSettings'] as const,
  },

  deploymentVersion: {
    backend: ['deploymentVersion', 'backend'] as const,
    frontend: ['deploymentVersion', 'frontend'] as const,
  },

  resources: {
    all: ['resources'] as const,
  },

  sessions: {
    taskRuns: ['session-task-runs'] as const,
  },

  timeline: {
    taskRuns: ['timeline-task-runs'] as const,
  },

  literature: {
    papers: (subscriptionId: string | null | undefined, unreadOnly: boolean) =>
      ['literature-papers', subscriptionId, unreadOnly] as const,
    subscriptions: ['literature-subscriptions'] as const,
  },

  admin: {
    users: ['admin', 'users'] as const,
  },

  collaborators: {
    byProject: (projectId: string | null) =>
      ['collaborators', projectId] as const,
  },

  envAccess: {
    byEnv: (envId: string | null) => ['envAccess', envId] as const,
  },

  files: {
    list: (environmentId: string | null, workspaceId: string | null, path?: string) =>
      path
        ? (['files', environmentId, workspaceId, path] as const)
        : (['files', environmentId, workspaceId] as const),
  },

  terminal: {
    session: ['terminal-session'] as const,
  },
};
