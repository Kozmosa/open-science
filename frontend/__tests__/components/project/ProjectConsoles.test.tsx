import { fireEvent, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { renderWithProviders } from '@/shared/test/render';
import { ProjectContextConsole, ProjectSettingsConsole } from '@features/projects';
import {
  acceptDomainContextCandidate,
  getDomainProjectContext,
  getDomainProjectContextCandidates,
  getDomainProjectContextVersions,
  getDomainProjectMembers,
  publishDomainProjectContext,
  saveDomainProjectContextDraft,
  type DomainProjectProjection,
} from '@features/domain';

vi.mock('@features/domain', async () => {
  const actual = await vi.importActual<typeof import('@features/domain')>('@features/domain');
  return {
    ...actual,
    acceptDomainContextCandidate: vi.fn(),
    getDomainProjectContext: vi.fn(),
    getDomainProjectContextCandidates: vi.fn(),
    getDomainProjectContextVersions: vi.fn(),
    getDomainProjectMembers: vi.fn(),
    publishDomainProjectContext: vi.fn(),
    saveDomainProjectContextDraft: vi.fn(),
  };
});

const project: DomainProjectProjection = {
  project_id: 'project-1', name: 'Paper Project', description: 'A project', status: 'active', is_default: false,
  owner_user_id: 'user-1', current_user_role: 'owner', created_at: '2026-07-14T00:00:00Z', updated_at: '2026-07-14T00:00:00Z', recent_activity_at: '2026-07-14T00:00:00Z',
  workspace_count: 1, executable_workspace_count: 1, task_count: 2, active_task_count: 1, running_task_count: 1,
  primary_workspace: null, attention_required: false, attention_reasons: [],
  permissions: { can_edit: true, can_publish: true, can_manage_members: true, can_archive: true, can_unarchive: false, can_create_task: true },
};

const version = {
  context_version_id: 'ctx-v1', project_id: 'project-1', content: 'Active context', fingerprint: 'fp-1', fragment_manifest: [], fragment_provenance_status: 'complete', fragment_provenance_evidence: {}, assembly_eligible: true, is_active: true, created_by_user_id: 'user-1', created_at: '2026-07-14T00:00:00Z',
};

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(getDomainProjectContext).mockResolvedValue({ project_id: 'project-1', active_version: version, draft: { content: 'Draft context', fingerprint: 'draft-fp', updated_by_user_id: 'user-1', updated_at: '2026-07-14T01:00:00Z' } });
  vi.mocked(getDomainProjectContextVersions).mockResolvedValue({ items: [version] });
  vi.mocked(getDomainProjectContextCandidates).mockResolvedValue({ items: [{ candidate_id: 'candidate-1', project_id: 'project-1', content: 'Candidate fact', status: 'pending', created_at: '2026-07-14T01:00:00Z', created_by_user_id: 'user-1', source_metadata: {}, source_task_id: null, source_attempt_id: null, accepted_by_user_id: null, accepted_at: null, rejected_by_user_id: null, rejected_at: null, rejection_reason: null }] });
  vi.mocked(getDomainProjectMembers).mockResolvedValue({ items: [] });
});

describe('Project F8 consoles', () => {
  it('saves Draft, publishes and accepts candidates through permission-gated mutations', async () => {
    const user = userEvent.setup();
    vi.mocked(saveDomainProjectContextDraft).mockResolvedValue({ project_id: 'project-1', active_version: version, draft: null });
    vi.mocked(publishDomainProjectContext).mockResolvedValue(version);
    vi.mocked(acceptDomainContextCandidate).mockResolvedValue({} as never);
    renderWithProviders(<ProjectContextConsole project={project} />);

    const draft = await screen.findByLabelText('Project Context draft');
    fireEvent.change(draft, { target: { value: 'Revised durable context' } });
    await user.click(screen.getByRole('button', { name: 'Save draft' }));
    await waitFor(() => expect(saveDomainProjectContextDraft).toHaveBeenCalledWith('project-1', 'Revised durable context', expect.stringContaining('project.context.draft')));
    await user.click(screen.getByRole('button', { name: 'Publish' }));
    await waitFor(() => expect(publishDomainProjectContext).toHaveBeenCalled());
    await user.click(screen.getByRole('button', { name: 'Accept' }));
    await waitFor(() => expect(acceptDomainContextCandidate).toHaveBeenCalledWith('project-1', 'candidate-1', expect.any(String)));
  });

  it('permanently disables Archive for the default Project', async () => {
    renderWithProviders(<ProjectSettingsConsole project={{ ...project, project_id: 'default', is_default: true, permissions: { ...project.permissions, can_archive: false } }} />);
    expect(await screen.findByText(/default Project is permanent/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Archive Project' })).toBeDisabled();
    expect(screen.getByLabelText('Member user ID')).toBeInTheDocument();
  });
});
