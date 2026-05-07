import { Plus, Search } from 'lucide-react';
import { useState } from 'react';
import { Button, Input } from '../ui';
import { useT } from '../../i18n';
import type { ProjectRecord } from '../../types';

interface Props {
  projects: ProjectRecord[];
  selectedProjectId: string | null;
  onSelectProject: (projectId: string) => void;
  onCreateProject: () => void;
}

export default function ProjectSidebar({
  projects,
  selectedProjectId,
  onSelectProject,
  onCreateProject,
}: Props) {
  const t = useT();
  const [searchQuery, setSearchQuery] = useState('');
  const filtered = projects.filter((p) =>
    p.name.toLowerCase().includes(searchQuery.toLowerCase())
  );

  return (
    <div className="flex h-full flex-col p-3">
      <div className="mb-3 flex items-start justify-between gap-3 border-b border-[var(--sidebar-border)] pb-3">
        <div className="min-w-0">
          <p className="text-xs font-medium uppercase tracking-wide text-[var(--text-secondary)]">
            {t('pages.projects.sidebarEyebrow')}
          </p>
          <h1 className="mt-1 truncate text-lg font-semibold tracking-tight text-[var(--sidebar-foreground)]">
            {t('pages.projects.sidebarTitle')}
          </h1>
          <p className="mt-1 text-xs text-[var(--text-secondary)]">
            {t('pages.projects.sidebarCount', { count: projects.length })}
          </p>
        </div>
        <Button
          onClick={onCreateProject}
          className="inline-flex h-9 items-center gap-2 px-3 shadow-sm"
        >
          <Plus size={15} />
          {t('pages.projects.newProject')}
        </Button>
      </div>

      <div className="relative mb-3">
        <Search size={14} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-[var(--text-tertiary)]" />
        <Input
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          placeholder={t('pages.projects.searchPlaceholder')}
          className="pl-8"
        />
      </div>

      <div className="flex-1 overflow-auto">
        {filtered.map((project) => (
          <button
            key={project.project_id}
            onClick={() => onSelectProject(project.project_id)}
            className={`w-full rounded-lg px-3 py-2 text-left text-sm transition
              ${selectedProjectId === project.project_id
                ? 'bg-[var(--sidebar-primary)] text-[var(--sidebar-primary-foreground)]'
                : 'text-[var(--muted-foreground)] hover:bg-[var(--sidebar-primary)] hover:text-[var(--sidebar-foreground)]'
              }`}
          >
            <div className="truncate font-medium">{project.name}</div>
            {project.description ? (
              <div className="truncate text-[11px] opacity-70">{project.description}</div>
            ) : null}
          </button>
        ))}
      </div>
    </div>
  );
}
