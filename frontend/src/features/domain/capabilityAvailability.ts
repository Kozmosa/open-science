import type {
  DomainCapabilities,
  DomainCapabilityAvailability,
  DomainCapabilityName,
} from './types';

export function capabilityAvailability(
  capabilities: DomainCapabilities | null,
  capability: DomainCapabilityName,
): DomainCapabilityAvailability {
  if (capabilities === null) {
    return { available: false, reason: 'OpenScience capabilities are still loading.' };
  }
  if (capabilities[capability]) {
    return { available: true, reason: null };
  }
  if (capability === 'standard_task_create' || capability === 'task_attempts') {
    if (capabilities.task_dispatcher.maintenance_active) {
      return { available: false, reason: 'Task execution is paused for maintenance.' };
    }
    if (capabilities.task_dispatcher.stale_participant_ids.length > 0) {
      return { available: false, reason: 'The task dispatcher heartbeat is stale.' };
    }
    if (capabilities.task_dispatcher.active_participant_ids.length === 0) {
      return { available: false, reason: 'No active task dispatcher is available.' };
    }
  }
  if (capability === 'overview_snapshot' && !capabilities.overview_snapshot_job_store) {
    return { available: false, reason: 'The overview snapshot store is unavailable.' };
  }
  const labels: Record<DomainCapabilityName, string> = {
    standard_task_create: 'Standard task creation',
    project_context: 'Project Context',
    workspace_links: 'Workspace linking',
    task_attempts: 'Task Attempt history',
    literature_research_task: 'Literature research tasks',
    overview_snapshot: 'Today overview',
  };
  return { available: false, reason: `${labels[capability]} is unavailable on this backend.` };
}
