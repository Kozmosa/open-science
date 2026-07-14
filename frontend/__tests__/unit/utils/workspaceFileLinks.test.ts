import { describe, expect, it } from 'vitest';
import {
  resolveWorkspaceFileRoute,
  workspaceFileBrowserHref,
} from '../../../src/shared/utils/workspaceFileLinks';

describe('workspace file links', () => {
  it('does not rewrite external HTTPS URLs as workspace files', () => {
    const target = 'https://browse-export.arxiv.org/abs/2605.24117';

    expect(resolveWorkspaceFileRoute(target)).toBeNull();
    expect(workspaceFileBrowserHref(target)).toBeNull();
  });

  it('does not rewrite other URI schemes as workspace files', () => {
    expect(resolveWorkspaceFileRoute('mailto:researcher@example.com')).toBeNull();
  });

  it('does not rewrite network-path URLs as workspace files', () => {
    expect(
      workspaceFileBrowserHref('//browse-export.arxiv.org/.ainrf_workspaces/default/paper.md')
    ).toBeNull();
  });

  it('rewrites relative paths to the default workspace browser route', () => {
    expect(workspaceFileBrowserHref('reports/result.md')).toBe(
      '/workspace-browser?workspace_id=workspace-default&path=reports%2Fresult.md'
    );
  });

  it('rewrites absolute workspace paths to their workspace browser route', () => {
    expect(resolveWorkspaceFileRoute('/home/user/.ainrf_workspaces/demo/reports/result.md')).toEqual({
      workspaceId: 'workspace-demo',
      path: 'reports/result.md',
    });
  });
});
