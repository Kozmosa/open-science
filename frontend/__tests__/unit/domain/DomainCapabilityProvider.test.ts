import { capabilityAvailability } from '@features/domain/capabilityAvailability';
import type { DomainCapabilities } from '@features/domain/types';

function capabilities(overrides: Partial<DomainCapabilities> = {}): DomainCapabilities {
  return {
    domain_contract_version: 2,
    mode: 'v2',
    standard_task_create: false,
    project_context: true,
    workspace_links: true,
    task_attempts: false,
    task_dispatcher: {
      participant_type: 'task-dispatcher',
      ready: false,
      maintenance_active: false,
      maintenance_epoch: null,
      stale_after_seconds: 30,
      registered_participant_ids: [],
      active_participant_ids: [],
      fresh_participant_ids: [],
      stale_participant_ids: [],
    },
    literature_research_task: false,
    overview_snapshot: false,
    overview_snapshot_job_store: true,
    overview_snapshot_planner: {
      job_store_ready: true,
      planner_ready: false,
      planner_status: 'unavailable',
    },
    ...overrides,
  };
}

describe('capabilityAvailability', () => {
  it('uses direct dispatcher evidence for disabled Task actions', () => {
    expect(capabilityAvailability(capabilities(), 'standard_task_create')).toEqual({
      available: false,
      reason: 'No active task dispatcher is available.',
    });
  });

  it('does not infer a capability from the common contract version', () => {
    expect(capabilityAvailability(capabilities(), 'literature_research_task')).toEqual({
      available: false,
      reason: 'Literature research tasks is unavailable on this backend.',
    });
  });
});
