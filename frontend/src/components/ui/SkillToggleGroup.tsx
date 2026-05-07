import type { SkillItem } from '../../types';
import type { SkillMode } from '../../settings/types';

interface Props {
  skills: SkillItem[];
  skillModes: Record<string, SkillMode>;
  onChange: (skillModes: Record<string, SkillMode>) => void;
}

const nextMode = (mode: SkillMode): SkillMode => {
  if (mode === 'disabled') return 'enabled';
  if (mode === 'enabled') return 'auto';
  return 'disabled';
};

const buttonClass = (mode: SkillMode): string => {
  switch (mode) {
    case 'enabled':
      return 'bg-[var(--apple-blue)] text-white';
    case 'auto':
      return 'bg-emerald-100 text-emerald-800';
    case 'disabled':
    default:
      return 'bg-[var(--bg-secondary)] text-[var(--text-tertiary)]';
  }
};

export default function SkillToggleGroup({ skills, skillModes, onChange }: Props) {
  const cycle = (skillId: string) => {
    const current = skillModes[skillId] ?? 'disabled';
    onChange({ ...skillModes, [skillId]: nextMode(current) });
  };

  const setAll = (mode: SkillMode) => {
    const next: Record<string, SkillMode> = {};
    for (const skill of skills) {
      next[skill.skill_id] = mode;
    }
    onChange(next);
  };

  return (
    <div className="space-y-2">
      <div className="flex gap-2">
        <button
          type="button"
          onClick={() => setAll('enabled')}
          disabled={skills.length === 0}
          className="rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-1.5 text-xs font-medium text-[var(--text)] transition hover:bg-[var(--bg-secondary)] disabled:opacity-40"
        >
          Enable All
        </button>
        <button
          type="button"
          onClick={() => setAll('disabled')}
          disabled={skills.length === 0}
          className="rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-1.5 text-xs font-medium text-[var(--text)] transition hover:bg-[var(--bg-secondary)] disabled:opacity-40"
        >
          Disable All
        </button>
        <button
          type="button"
          onClick={() => setAll('auto')}
          disabled={skills.length === 0}
          className="rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-1.5 text-xs font-medium text-[var(--text)] transition hover:bg-[var(--bg-secondary)] disabled:opacity-40"
        >
          Auto All
        </button>
      </div>
      <div className="flex flex-wrap gap-2">
        {skills.map((skill) => {
          const mode = skillModes[skill.skill_id] ?? 'disabled';
          return (
            <button
              key={skill.skill_id}
              type="button"
              onClick={() => cycle(skill.skill_id)}
              title={skill.description ?? skill.label}
              className={[
                'inline-flex items-center rounded-full px-3 py-1.5 text-xs font-medium transition',
                buttonClass(mode),
              ].join(' ')}
            >
              {skill.label}
              <span className="ml-1.5 rounded px-1 py-0.5 text-[10px] font-semibold uppercase opacity-80">
                {mode}
              </span>
            </button>
          );
        })}
      </div>
    </div>
  );
}
