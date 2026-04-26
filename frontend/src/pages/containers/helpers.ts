import type {
  EnvironmentAuthKind,
  EnvironmentCreateRequest,
  EnvironmentListResponse,
  EnvironmentRecord,
  EnvironmentUpdateRequest,
  ProjectEnvironmentReference,
  ProjectEnvironmentReferenceCreateRequest,
  ProjectEnvironmentReferenceListResponse,
  ProjectEnvironmentReferenceUpdateRequest,
} from '../../types';

export const environmentsQueryKey = ['environments'] as const;
export const projectEnvironmentRefsQueryKey = ['project-environment-refs', 'default'] as const;
export const EMPTY_ENVIRONMENTS: EnvironmentRecord[] = [];
export const EMPTY_PROJECT_REFS: ProjectEnvironmentReference[] = [];
export const defaultProjectId = 'default';

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

export interface ProjectRefFormValues {
  override_workdir: string;
  override_env_name: string;
  override_env_manager: string;
  override_runtime_notes: string;
}

export function valuesFromProjectReference(
  reference: ProjectEnvironmentReference | null
): ProjectRefFormValues {
  return {
    override_workdir: reference?.override_workdir ?? '',
    override_env_name: reference?.override_env_name ?? '',
    override_env_manager: reference?.override_env_manager ?? '',
    override_runtime_notes: reference?.override_runtime_notes ?? '',
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
): EnvironmentCreateRequest {
  const request = {
    alias: values.alias.trim(),
    display_name: values.display_name.trim(),
    description: values.description.trim() || null,
    tags: parseTags(values.tags),
    host: values.host.trim(),
    port: Number.parseInt(values.port, 10),
    user: values.user.trim() || 'root',
    auth_kind: values.auth_kind,
    identity_file: values.identity_file.trim() || null,
    proxy_jump: values.proxy_jump.trim() || null,
    proxy_command: values.proxy_command.trim() || null,
    ssh_options: parseJsonObject(
      values.ssh_options,
      errorMessages.sshOptionsObjectError,
      errorMessages.sshOptionsValuesError
    ),
    default_workdir: values.default_workdir.trim() || null,
    preferred_python: values.preferred_python.trim() || null,
    preferred_env_manager: values.preferred_env_manager.trim() || null,
    preferred_runtime_notes: values.preferred_runtime_notes.trim() || null,
    task_harness_profile: values.task_harness_profile.trim() || null,
  } satisfies EnvironmentCreateRequest;

  if (!Number.isInteger(request.port) || request.port < 1 || request.port > 65535) {
    throw new Error(errorMessages.portRangeError);
  }

  return request;
}

export function buildProjectReferenceUpdateRequest(
  values: ProjectRefFormValues
): ProjectEnvironmentReferenceUpdateRequest {
  return {
    override_workdir: values.override_workdir.trim() || null,
    override_env_name: values.override_env_name.trim() || null,
    override_env_manager: values.override_env_manager.trim() || null,
    override_runtime_notes: values.override_runtime_notes.trim() || null,
  };
}

export function buildProjectReferenceCreateRequest(
  environmentId: string,
  payload: ProjectEnvironmentReferenceUpdateRequest
): ProjectEnvironmentReferenceCreateRequest {
  return {
    environment_id: environmentId,
    is_default: payload.is_default ?? false,
    override_workdir: payload.override_workdir ?? null,
    override_env_name: payload.override_env_name ?? null,
    override_env_manager: payload.override_env_manager ?? null,
    override_runtime_notes: payload.override_runtime_notes ?? null,
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

export function toEnvironmentUpdateRequest(
  request: EnvironmentCreateRequest
): EnvironmentUpdateRequest {
  return request;
}
