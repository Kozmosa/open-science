import type { Locale } from '@/shared/i18n/messages';

type ProjectionReason =
  | 'no_workspace'
  | 'no_executable_workspace'
  | 'failed_tasks'
  | 'environment_disabled'
  | 'environment_grant_required'
  | 'project_archived'
  | 'workspace_unregistered'
  | 'workspace_link_inactive'
  | 'owner_required';

const projectionReasonAliases: Record<string, ProjectionReason> = {
  no_workspace: 'no_workspace',
  no_executable_workspace: 'no_executable_workspace',
  failed_tasks: 'failed_tasks',
  environment_disabled: 'environment_disabled',
  environment_grant_required: 'environment_grant_required',
  environment_grant_missing: 'environment_grant_required',
  'active Environment grant is required': 'environment_grant_required',
  project_archived: 'project_archived',
  workspace_unregistered: 'workspace_unregistered',
  workspace_link_inactive: 'workspace_link_inactive',
  owner_required: 'owner_required',
  tenant_owner_required: 'owner_required',
};

const projectionReasonLabels: Record<Locale, Record<ProjectionReason | 'unknown', string>> = {
  en: {
    no_workspace: 'No Workspace is linked to this Project.',
    no_executable_workspace: 'No linked Workspace is currently executable.',
    failed_tasks: 'One or more Tasks need attention after failing.',
    environment_disabled: 'The Workspace Environment is disabled.',
    environment_grant_required: 'An active Environment grant is required.',
    project_archived: 'The linked Project is archived.',
    workspace_unregistered: 'The Workspace is no longer registered.',
    workspace_link_inactive: 'The Project–Workspace link is inactive.',
    owner_required: 'Workspace owner permission is required.',
    unknown: 'The execution requirement is unavailable.',
  },
  zh: {
    no_workspace: '此项目尚未关联工作区。',
    no_executable_workspace: '当前没有可执行的已关联工作区。',
    failed_tasks: '一个或多个任务失败，需要处理。',
    environment_disabled: '工作区所属环境已停用。',
    environment_grant_required: '需要有效的环境执行授权。',
    project_archived: '关联项目已归档。',
    workspace_unregistered: '工作区已注销。',
    workspace_link_inactive: '项目与工作区的关联已失效。',
    owner_required: '此操作需要工作区所有者权限。',
    unknown: '暂时无法确定不可执行原因。',
  },
};

function humanizeIdentifier(value: string): string {
  const normalized = value.trim().replace(/[-_]+/g, ' ');
  if (!normalized) return '';
  return normalized.replace(/\b\w/g, (letter) => letter.toUpperCase());
}

export function projectionReasonLabel(
  locale: Locale,
  reason: string | null | undefined,
): string {
  if (!reason) return projectionReasonLabels[locale].unknown;
  const canonicalReason = projectionReasonAliases[reason];
  if (canonicalReason) return projectionReasonLabels[locale][canonicalReason];
  return /^[a-z0-9_-]+$/i.test(reason) ? humanizeIdentifier(reason) : reason;
}

export function projectionReasonList(
  locale: Locale,
  reasons: Array<string | null | undefined>,
): string[] {
  return [...new Set(reasons.filter((reason): reason is string => Boolean(reason)))]
    .map((reason) => projectionReasonLabel(locale, reason));
}
