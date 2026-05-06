import type { SkillItem } from '../../types';

interface Props {
  skills: SkillItem[];
  selected: string[];
  onChange: (selected: string[]) => void;
}

const badgeClass = (mode: string) => {
  switch (mode) {
    case 'auto':
      return 'bg-emerald-100 text-emerald-800';
    case 'prompt_only':
      return 'bg-amber-100 text-amber-800';
    case 'disabled':
      return 'bg-gray-100 text-gray-600';
    default:
      return 'bg-gray-100 text-gray-600';
  }
};

export default function SkillToggleGroup({ skills, selected, onChange }: Props) {
  const selectedSet = new Set(selected);

  const toggle = (skillId: string) => {
    const next = new Set(selectedSet);
    if (next.has(skillId)) {
      next.delete(skillId);
    } else {
      next.add(skillId);
    }
    onChange(Array.from(next));
  };

  return (
    <div className="flex flex-wrap gap-2">
      {skills.map((skill) => {
        const isSelected = selectedSet.has(skill.skill_id);
        return (
          <button
            key={skill.skill_id}
            type="button"
            onClick={() => toggle(skill.skill_id)}
            title={skill.description ?? skill.label}
            className={[
              'inline-flex items-center rounded-full px-3 py-1.5 text-xs font-medium transition',
              isSelected
                ? 'bg-[var(--apple-blue)] text-white'
                : 'bg-[var(--bg-secondary)] text-[var(--text-secondary)] hover:bg-[var(--bg-tertiary)]',
            ].join(' ')}
          >
            {skill.label}
            <span
              className={[
                'ml-1.5 rounded px-1 py-0.5 text-[10px] font-semibold',
                badgeClass(skill.inject_mode),
              ].join(' ')}
            >
              {skill.inject_mode}
            </span>
          </button>
        );
      })}
    </div>
  );
}
