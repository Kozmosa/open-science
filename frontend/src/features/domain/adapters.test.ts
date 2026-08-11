import { describe, expect, it } from 'vitest';
import type {
  DomainCapabilitiesResponse,
  DomainContextCandidateAcceptResponse,
  DomainContextCandidateResponse,
  DomainProjectSummaryResponse,
  DomainWorkspaceResponse,
} from '@/generated/transport';
import {
  adaptDomainCapabilities,
  adaptDomainContextCandidate,
  adaptDomainContextCandidateAcceptance,
  adaptDomainProject,
  adaptDomainWorkspace,
} from './adapters';

describe('Domain transport adapters', () => {
  it('normalizes optional project and workspace projection fields at one seam', () => {
    const project: DomainProjectSummaryResponse = {
      project_id: 'project-1',
      name: 'Project',
      status: 'active',
      is_default: false,
      owner_user_id: 'user-1',
      current_user_role: 'owner',
      created_at: '2026-08-11T00:00:00Z',
      updated_at: '2026-08-11T00:00:00Z',
      recent_activity_at: '2026-08-11T00:00:00Z',
      workspace_count: 0,
      executable_workspace_count: 0,
      task_count: 0,
      active_task_count: 0,
      running_task_count: 0,
      attention_required: false,
      permissions: {
        can_edit: true,
        can_publish: true,
        can_manage_members: true,
        can_archive: true,
        can_unarchive: false,
        can_create_task: false,
      },
    };
    const workspace: DomainWorkspaceResponse = {
      workspace_id: 'workspace-1',
      label: 'Workspace',
      canonical_path: '/workspace',
      status: 'active',
      owner_user_id: 'user-1',
      created_at: '2026-08-11T00:00:00Z',
      updated_at: '2026-08-11T00:00:00Z',
      recent_activity_at: '2026-08-11T00:00:00Z',
      environment: {
        environment_id: 'env-1',
        alias: 'local',
        display_name: 'Local',
        status: 'active',
      },
      task_count: 0,
      active_task_count: 0,
      can_execute: true,
      can_manage_registry: true,
      git_status: { state: 'not_collected' },
    };

    expect(adaptDomainProject(project)).toMatchObject({
      description: null,
      primary_workspace: null,
      attention_reasons: [],
    });
    expect(adaptDomainWorkspace(workspace)).toMatchObject({
      description: null,
      workspace_context: null,
      project_links: [],
      cannot_execute_reason: null,
      git_status: { branch: null, is_dirty: null, observed_at: null },
    });
  });

  it('preserves the canonical proposed candidate state and unwraps acceptance', () => {
    const proposed: DomainContextCandidateResponse = {
      candidate_id: 'candidate-1',
      project_id: 'project-1',
      content: 'Finding',
      status: 'proposed',
      created_at: '2026-08-11T00:00:00Z',
      created_by_user_id: 'user-1',
      source_metadata: {},
      source_task_id: 'task-1',
      accepted_by_user_id: null,
      accepted_at: null,
      rejected_by_user_id: null,
      rejected_at: null,
      rejection_reason: null,
    };
    const response: DomainContextCandidateAcceptResponse = {
      candidate: {
        ...proposed,
        status: 'accepted',
        accepted_by_user_id: 'user-2',
        accepted_at: '2026-08-11T00:01:00Z',
      },
      draft: {
        content: 'Draft',
        fingerprint: 'fingerprint',
        updated_by_user_id: 'user-1',
        updated_at: '2026-08-11T00:00:00Z',
      },
    };

    const accepted = adaptDomainContextCandidateAcceptance(response);
    expect(adaptDomainContextCandidate(proposed).status).toBe('proposed');
    expect(accepted.candidate.status).toBe('accepted');
    expect(accepted.draft?.content).toBe('Draft');
    expect(accepted.candidate).not.toHaveProperty('source_output_start_seq');
  });

  it('normalizes optional planner diagnostics without widening transport enums', () => {
    const response: DomainCapabilitiesResponse = {
      domain_contract_version: 2,
      mode: 'v2',
      standard_task_create: true,
      project_context: true,
      workspace_links: true,
      task_dispatcher: {
        participant_type: 'task-dispatcher',
        ready: true,
        maintenance_active: false,
        maintenance_epoch: 1,
        stale_after_seconds: 30,
        registered_participant_ids: ['dispatcher-1'],
        active_participant_ids: ['dispatcher-1'],
        fresh_participant_ids: ['dispatcher-1'],
        stale_participant_ids: [],
      },
      literature_research_task: true,
      overview_snapshot: true,
      overview_snapshot_job_store: true,
      overview_snapshot_planner: {
        job_store_ready: true,
        planner_ready: true,
        planner_status: 'running',
      },
    };

    expect(adaptDomainCapabilities(response).overview_snapshot_planner).toMatchObject({
      planner_status: 'running',
      planner_id: null,
      heartbeat_at: null,
      last_schedule_at: null,
      last_error: null,
    });
  });
});
