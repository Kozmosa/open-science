import type {
  EnvironmentAuthKind,
  EnvironmentListResponse,
  EnvironmentMutationInput,
  EnvironmentRecord,
  ProjectEnvironmentReference,
  ProjectEnvironmentReferenceCreateInput,
  ProjectEnvironmentReferenceListResponse,
  ProjectEnvironmentReferenceUpdateInput,
} from '../../types';

export type EnvironmentEditorMode = 'create' | 'edit';

export interface EnvironmentFormValues {
  alias: string;
  display_name: string;
  description: string;
  tags: string;
  host: string;
  port: string;
  user: string;
  auth_kind: EnvironmentAuthKind;
  identity_file: string;
  proxy_jump: string;
  proxy_command: string;
  ssh_options: string;
  default_workdir: string;
  preferred_python: string;
  preferred_env_manager: string;
  preferred_runtime_notes: string;
  task_harness_profile: string;
}

export const emptyFormValues = (): EnvironmentFormValues => ({
  alias: '',
  display_name: '',
  description: '',
  tags: '',
  host: '',
  port: '22',
  user: 'root',
  auth_kind: 'ssh_key',
  identity_file: '',
  proxy_jump: '',
  proxy_command: '',
  ssh_options: '{}',
  default_workdir: '',
  preferred_python: '',
  preferred_env_manager: '',
  preferred_runtime_notes: '',
  task_harness_profile: '',
});

export function valuesFromEnvironment(environment: EnvironmentRecord): EnvironmentFormValues {
  return {
    alias: environment.alias,
    display_name: environment.display_name,
    description: environment.description ?? '',
    tags: environment.tags.join(', '),
    host: environment.host,
    port: String(environment.port),
    user: environment.user,
    auth_kind: environment.auth_kind,
    identity_file: environment.identity_file ?? '',
    proxy_jump: environment.proxy_jump ?? '',
    proxy_command: environment.proxy_command ?? '',
    ssh_options: JSON.stringify(environment.ssh_options, null, 2),
    default_workdir: environment.default_workdir ?? '',
    preferred_python: environment.preferred_python ?? '',
    preferred_env_manager: environment.preferred_env_manager ?? '',
    preferred_runtime_notes: environment.preferred_runtime_notes ?? '',
    task_harness_profile: environment.task_harness_profile ?? '',
  };
}

export function parseTags(value: string): string[] {
  return value
    .split(',')
    .map((item) => item.trim())
    .filter((item) => item.length > 0);
}

export function parseJsonObject(
  value: string,
  objectErrorMessage: string,
  valuesErrorMessage: string
): Record<string, string> {
  const trimmed = value.trim();
  if (!trimmed) {
    return {};
  }

  let parsed: unknown;
  try {
    parsed = JSON.parse(trimmed) as unknown;
  } catch {
    throw new Error(objectErrorMessage);
  }
  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
    throw new Error(objectErrorMessage);
  }

  const entries = Object.entries(parsed as Record<string, unknown>);
  const normalized: Record<string, string> = {};
  for (const [key, entryValue] of entries) {
    if (typeof entryValue !== 'string') {
      throw new Error(valuesErrorMessage);
    }
    normalized[key] = entryValue;
  }
  return normalized;
}

export function buildEnvironmentRequest(
  values: EnvironmentFormValues,
  errorMessages: {
    portRangeError: string;
    sshOptionsObjectError: string;
    sshOptionsValuesError: string;
  }
): EnvironmentMutationInput {
  const request = {
    alias: values.alias.trim(),
    displayName: values.display_name.trim(),
    description: values.description.trim() || null,
    tags: parseTags(values.tags),
    host: values.host.trim(),
    port: Number.parseInt(values.port, 10),
    user: values.user.trim() || 'root',
    authKind: values.auth_kind,
    identityFile: values.identity_file.trim() || null,
    proxyJump: values.proxy_jump.trim() || null,
    proxyCommand: values.proxy_command.trim() || null,
    sshOptions: parseJsonObject(
      values.ssh_options,
      errorMessages.sshOptionsObjectError,
      errorMessages.sshOptionsValuesError
    ),
    defaultWorkdir: values.default_workdir.trim() || null,
    preferredPython: values.preferred_python.trim() || null,
    preferredEnvManager: values.preferred_env_manager.trim() || null,
    preferredRuntimeNotes: values.preferred_runtime_notes.trim() || null,
    taskHarnessProfile: values.task_harness_profile.trim() || null,
  } satisfies EnvironmentMutationInput;

  if (!Number.isInteger(request.port) || request.port < 1 || request.port > 65535) {
    throw new Error(errorMessages.portRangeError);
  }

  return request;
}

export function buildProjectReferenceCreateRequest(
  environmentId: string,
  payload: ProjectEnvironmentReferenceUpdateInput
): ProjectEnvironmentReferenceCreateInput {
  return {
    environmentId,
    isDefault: payload.isDefault ?? false,
    overrideWorkdir: payload.overrideWorkdir,
    overrideEnvName: payload.overrideEnvName,
    overrideEnvManager: payload.overrideEnvManager,
    overrideRuntimeNotes: payload.overrideRuntimeNotes,
  };
}

export function formatTimestamp(value: string | null, locale: string, neverLabel: string): string {
  if (!value) {
    return neverLabel;
  }

  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return value;
  }

  return parsed.toLocaleString(locale === 'zh' ? 'zh-CN' : 'en-US');
}

export function mergeEnvironmentList(
  current: EnvironmentListResponse | undefined,
  environment: EnvironmentRecord
): EnvironmentListResponse {
  const items = current?.items ?? [];
  const nextItems = [...items];
  const index = nextItems.findIndex((item) => item.id === environment.id);
  if (index === -1) {
    nextItems.unshift(environment);
  } else {
    nextItems[index] = environment;
  }
  return { items: nextItems };
}

export function removeEnvironmentFromList(
  current: EnvironmentListResponse | undefined,
  environmentId: string
): EnvironmentListResponse {
  return {
    items: (current?.items ?? []).filter((item) => item.id !== environmentId),
  };
}

export function mergeProjectReferenceList(
  current: ProjectEnvironmentReferenceListResponse | undefined,
  reference: ProjectEnvironmentReference
): ProjectEnvironmentReferenceListResponse {
  const items = (current?.items ?? [])
    .filter((item) => item.environment_id !== reference.environment_id)
    .map((item) => (reference.is_default ? { ...item, is_default: false } : item));
  return { items: [...items, reference] };
}

export function removeProjectReferenceFromList(
  current: ProjectEnvironmentReferenceListResponse | undefined,
  environmentId: string
): ProjectEnvironmentReferenceListResponse {
  return {
    items: (current?.items ?? []).filter((item) => item.environment_id !== environmentId),
  };
}
