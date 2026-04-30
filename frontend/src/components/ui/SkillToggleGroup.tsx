import type { SkillItem } from '../../types';

interface Props {
  skills: SkillItem[];
  selected: string[];
  onChange: (selected: string[]) => void;
}

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
          </button>
        );
      })}
    </div>
  );
}
