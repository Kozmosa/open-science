import { Folder } from 'lucide-react';
import { useT } from '@/shared/i18n';
import type { ProjectRecord } from '@/shared/types';

interface ProjectDropZoneProps {
  projects: ProjectRecord[];
  visible: boolean;
  currentProjectId: string;
}

/**
 * Floating left-edge drop-target panel revealed while dragging a task node.
 *
 * The cards are plain elements tagged with `data-project-id`; the parent canvas
 * performs the actual hit-test on drag-stop via `document.elementsFromPoint`,
 * because React Flow drives node dragging with pointer events (not HTML5 DnD).
 */
export default function ProjectDropZone({
  projects = [],
  visible,
  currentProjectId,
}: ProjectDropZoneProps) {
  const t = useT();
  const others = projects.filter((p) => p.project_id !== currentProjectId);

  return (
    <div
      className={`pointer-events-none absolute left-0 top-0 bottom-0 z-30 w-56 overflow-y-auto border-r border-[var(--border)] bg-[var(--prism-glass)] backdrop-blur-xl p-3 shadow-[var(--shadow-pane)] transition-transform duration-300 ease-out ${
        visible ? 'translate-x-0' : '-translate-x-full'
      }`}
      aria-hidden={!visible}
    >
      <p className="mb-2 px-1 text-[11px] font-semibold uppercase tracking-widest text-[var(--text-tertiary)]">
        {t('pages.projects.moveToProject')}
      </p>
      <div className="flex flex-col gap-2">
        {others.map((project, i) => (
          <div
            key={project.project_id}
            data-project-id={project.project_id}
            style={{ transitionDelay: `${i * 40}ms` }}
            className={`rounded-lg border-2 bg-[var(--bg)] p-3 transition-all duration-200 hover:scale-[1.03] hover:border-[var(--prism-primary)] hover:shadow-md ${
              visible ? 'translate-y-0 opacity-100' : 'translate-y-1 opacity-0'
            }`}
          >
            <div className="flex items-center gap-2">
              <Folder size={15} className="shrink-0 text-[var(--prism-primary)]" />
              <div className="min-w-0">
                <div className="truncate text-sm font-medium text-[var(--text)]">{project.name}</div>
                {project.description ? (
                  <div className="truncate text-[11px] text-[var(--text-secondary)]">
                    {project.description}
                  </div>
                ) : null}
              </div>
            </div>
          </div>
        ))}
        {others.length === 0 ? (
          <p className="px-1 text-xs text-[var(--text-secondary)]">
            {t('pages.projects.noOtherProjects')}
          </p>
        ) : null}
      </div>
    </div>
  );
}
