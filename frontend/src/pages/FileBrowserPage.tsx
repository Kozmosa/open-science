import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { FolderOpen, RefreshCw } from 'lucide-react';
import { buildFileStreamUrl, listFiles, readFile, getWorkspaces } from '@/shared/api';
import { FileTree, FileViewer } from '../components/file-browser';
import { useEnvironmentSelection } from '../components/environment';
import { PageShell, SplitPane } from '@design-system/layout';
import { NativeSelect } from '@design-system/primitives';
import { useT } from '@/shared/i18n';
import type { FileEntry, FileReadResponse } from '@/shared/types';
import { queryKeys } from '@/shared/api/queryKeys';

const FILE_TREE_DEFAULT_WIDTH = 288;
const FILE_TREE_MIN_WIDTH = 200;


function normalizeRoutePath(path: string | null): string | null {
  if (!path) return null;
  return path.replace(/^\/+/, '');
}

export default function FileBrowserPage() {
  const t = useT();
  const [searchParams] = useSearchParams();
  const routeWorkspaceId = searchParams.get('workspace_id') ?? '';
  const routeEnvironmentId = searchParams.get('environment_id');
  const routePath = useMemo(() => normalizeRoutePath(searchParams.get('path')), [searchParams]);
  const queryClient = useQueryClient();
  const environmentSelection = useEnvironmentSelection();
  const selectedEnvironment = environmentSelection.selectedEnvironment;
  const environmentId = selectedEnvironment?.id ?? null;

  const workspacesQuery = useQuery({
    queryKey: queryKeys.workspaces.all,
    queryFn: getWorkspaces,
  });
  const workspaces = workspacesQuery.data?.items ?? [];

  const [selectedWorkspaceId, setSelectedWorkspaceId] = useState<string>(routeWorkspaceId);
  const effectiveWorkspaceId = selectedWorkspaceId || workspaces[0]?.workspace_id || '';

  const [selectedPath, setSelectedPath] = useState<string | null>(null);
  const [currentFile, setCurrentFile] = useState<FileReadResponse | null>(null);
  const [isFileLoading, setIsFileLoading] = useState(false);
  const [sidebarWidth, setSidebarWidth] = useState(FILE_TREE_DEFAULT_WIDTH);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);

  const rootQuery = useQuery({
    queryKey: queryKeys.files.list(environmentId, effectiveWorkspaceId),
    queryFn: () =>
      environmentId
        ? listFiles(environmentId, '', effectiveWorkspaceId || undefined)
        : Promise.resolve({ path: '', entries: [] }),
    enabled: !!environmentId,
  });

  const handleLoadDirectory = useCallback(
    async (path: string): Promise<FileEntry[]> => {
      if (!environmentId) return [];
      const result = await listFiles(
        environmentId,
        path,
        effectiveWorkspaceId || undefined
      );
      return result.entries;
    },
    [environmentId, effectiveWorkspaceId]
  );

  const handleSelectFile = useCallback(
    async (path: string) => {
      setSelectedPath(path);
      if (!environmentId) return;

      const entry = findEntryInTree(rootQuery.data?.entries ?? [], path);
      if (entry?.kind === 'directory') return;

      setIsFileLoading(true);
      try {
        const file = await readFile(
          environmentId,
          path,
          effectiveWorkspaceId || undefined
        );
        setCurrentFile(file);
      } catch {
        setCurrentFile(null);
      } finally {
        setIsFileLoading(false);
      }
    },
    [environmentId, effectiveWorkspaceId, rootQuery.data]
  );

  const openedRouteKeyRef = useRef<string | null>(null);

  useEffect(() => {
    if (routeEnvironmentId && routeEnvironmentId !== environmentId) {
      environmentSelection.onSelectEnvironment(routeEnvironmentId);
    }
  }, [environmentId, environmentSelection, routeEnvironmentId]);

  useEffect(() => {
    if (routeWorkspaceId && routeWorkspaceId !== selectedWorkspaceId) {
      setSelectedWorkspaceId(routeWorkspaceId);
    }
  }, [routeWorkspaceId, selectedWorkspaceId]);

  useEffect(() => {
    if (!environmentId || !effectiveWorkspaceId || !routePath) {
      return;
    }
    const routeKey = `${environmentId}:${effectiveWorkspaceId}:${routePath}`;
    if (openedRouteKeyRef.current === routeKey) {
      return;
    }
    openedRouteKeyRef.current = routeKey;
    void handleSelectFile(routePath);
  }, [effectiveWorkspaceId, environmentId, handleSelectFile, routePath]);

  const handleRefresh = useCallback(() => {
    if (!environmentId) return;
    queryClient.invalidateQueries({
      queryKey: queryKeys.files.list(environmentId, effectiveWorkspaceId),
    });
    setSelectedPath(null);
    setCurrentFile(null);
  }, [environmentId, effectiveWorkspaceId, queryClient]);

  const lastSidebarWidthRef = useRef(FILE_TREE_DEFAULT_WIDTH);

  const handleToggleSidebar = useCallback(() => {
    setSidebarCollapsed((prev) => {
      if (prev) {
        setSidebarWidth(lastSidebarWidthRef.current);
      } else {
        if (sidebarWidth > 44) {
          lastSidebarWidthRef.current = sidebarWidth;
        }
        setSidebarWidth(44);
      }
      return !prev;
    });
  }, [sidebarWidth]);

  const breadcrumb = selectedPath
    ? selectedPath.split('/').filter(Boolean)
    : [];

  return (
    <PageShell>
      {!selectedEnvironment ? (
        <div className="flex flex-1 items-center justify-center">
          <p className="text-sm text-[var(--text-tertiary)]">
            {t('pages.sessions.fileBrowser.selectEnv')}
          </p>
        </div>
      ) : rootQuery.isLoading ? (
        <div className="flex flex-1 items-center justify-center">
          <p className="text-sm text-[var(--text-tertiary)]">{t('pages.sessions.fileBrowser.loading')}</p>
        </div>
      ) : (
        <SplitPane
          sidebarMinWidth={FILE_TREE_MIN_WIDTH}
          sidebarWidth={sidebarWidth}
          onSidebarWidthChange={(w) => {
            setSidebarWidth(w);
            setSidebarCollapsed(false);
          }}
          className="flex-1"
          sidebar={
            <div className="flex h-full flex-col">
              <div className="flex items-center justify-between border-b border-[var(--border)] px-2 py-2">
                <button
                  type="button"
                  onClick={handleToggleSidebar}
                  className="inline-flex items-center gap-2 rounded p-1 text-[var(--text-secondary)] transition hover:bg-[var(--bg-secondary)] hover:text-[var(--text)]"
                  title={sidebarCollapsed ? t('layout.expandSidebar') : t('layout.collapseSidebar')}
                >
                  <FolderOpen className="h-4 w-4 shrink-0 text-[var(--apple-blue)]" />
                  {!sidebarCollapsed && (
                    <>
                      <span className="text-xs font-medium text-[var(--text)]">{t('pages.sessions.fileBrowser.files')}</span>
                    </>
                  )}
                </button>
                {!sidebarCollapsed && (
                  <button
                    type="button"
                    onClick={handleRefresh}
                    className="rounded p-1 text-[var(--text-tertiary)] transition hover:bg-[var(--bg-secondary)] hover:text-[var(--text)]"
                    title={t('pages.sessions.fileBrowser.refresh')}
                  >
                    <RefreshCw className="h-3.5 w-3.5" />
                  </button>
                )}
              </div>
              {!sidebarCollapsed && (
                <>
                  <div className="flex-1 overflow-auto p-2">
                    <FileTree
                      entries={rootQuery.data?.entries ?? []}
                      selectedPath={selectedPath}
                      onSelectFile={handleSelectFile}
                      onLoadDirectory={handleLoadDirectory}
                    />
                  </div>
                  <div className="border-t border-[var(--border)] px-3 py-2">
                    <NativeSelect
                      value={effectiveWorkspaceId}
                      onChange={(event) => setSelectedWorkspaceId(event.target.value)}
                      disabled={workspaces.length === 0}
                    >
                      {workspaces.map((workspace) => (
                        <option key={workspace.workspace_id} value={workspace.workspace_id}>
                          {workspace.label}
                        </option>
                      ))}
                    </NativeSelect>
                  </div>
                </>
              )}
            </div>
          }
        >
          <div className="flex h-full flex-col">
            <div className="flex items-center gap-2 border-b border-[var(--border)] px-4 py-2 text-xs text-[var(--text-secondary)]">
              {breadcrumb.length > 0 ? (
                breadcrumb.map((segment, index) => (
                  <span key={index} className="flex items-center gap-1">
                    {index > 0 && (
                      <span className="text-[var(--text-tertiary)]">/</span>
                    )}
                    <span
                      className={
                        index === breadcrumb.length - 1
                          ? 'font-medium text-[var(--text)]'
                          : ''
                      }
                    >
                      {segment}
                    </span>
                  </span>
                ))
              ) : (
                <span className="text-[var(--text-tertiary)]">{t('pages.sessions.fileBrowser.noFileSelected')}</span>
              )}
            </div>
            <div className="flex-1 overflow-hidden">
              <FileViewer
                file={currentFile}
                isLoading={isFileLoading}
                pdfStreamUrl={
                  currentFile?.mime_type === 'application/pdf' && environmentId
                    ? buildFileStreamUrl(
                        environmentId,
                        currentFile.path,
                        effectiveWorkspaceId || undefined
                      )
                    : undefined
                }
              />
            </div>
          </div>
        </SplitPane>
      )}
    </PageShell>
  );
}

function findEntryInTree(entries: FileEntry[], path: string): FileEntry | null {
  for (const entry of entries) {
    if (entry.path === path) return entry;
  }
  return null;
}
