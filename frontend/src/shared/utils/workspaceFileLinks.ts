const WORKSPACE_ROOT_MARKER = '/.ainrf_workspaces/';

export interface WorkspaceFileRoute {
  workspaceId: string;
  path: string;
}

function stripLeadingSlash(value: string): string {
  return value.replace(/^\/+/, '');
}

export function resolveWorkspaceFileRoute(target: string): WorkspaceFileRoute | null {
  if (target.length === 0) {
    return null;
  }

  if (!target.startsWith('/')) {
    return {
      workspaceId: 'workspace-default',
      path: stripLeadingSlash(target),
    };
  }

  const markerIndex = target.indexOf(WORKSPACE_ROOT_MARKER);
  if (markerIndex === -1) {
    return null;
  }

  const afterMarker = target.slice(markerIndex + WORKSPACE_ROOT_MARKER.length);
  const slashIndex = afterMarker.indexOf('/');
  if (slashIndex <= 0 || slashIndex === afterMarker.length - 1) {
    return null;
  }

  const workspaceSlug = afterMarker.slice(0, slashIndex);
  const relativePath = afterMarker.slice(slashIndex + 1);
  return {
    workspaceId: `workspace-${workspaceSlug}`,
    path: relativePath,
  };
}

export function buildWorkspaceFileBrowserPath(route: WorkspaceFileRoute): string {
  const params = new URLSearchParams();
  params.set('workspace_id', route.workspaceId);
  params.set('path', route.path);
  return `/workspace-browser?${params.toString()}`;
}

export function workspaceFileBrowserHref(target: string): string | null {
  const route = resolveWorkspaceFileRoute(target);
  return route ? buildWorkspaceFileBrowserPath(route) : null;
}
