import { useEffect, useMemo, useState } from 'react';
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

const buttonClass = (mode: SkillMode | 'mixed'): string => {
  switch (mode) {
    case 'enabled':
      return 'bg-[var(--apple-blue)] text-white';
    case 'auto':
      return 'bg-emerald-100 text-emerald-800';
    case 'mixed':
      return 'bg-amber-100 text-amber-800';
    case 'disabled':
    default:
      return 'bg-[var(--bg-secondary)] text-[var(--text-tertiary)]';
  }
};

function getGroupMode(
  skillModes: Record<string, SkillMode>,
  skillIds: string[]
): SkillMode | 'mixed' {
  const modes = skillIds.map((id) => skillModes[id] ?? 'disabled');
  if (modes.length === 0) return 'disabled';
  const first = modes[0];
  if (modes.every((m) => m === first)) return first;
  return 'mixed';
}

export default function SkillToggleGroup({ skills, skillModes, onChange }: Props) {
  const groups = useMemo(() => {
    const map = new Map<string, SkillItem[]>();
    const ungrouped: SkillItem[] = [];

    for (const skill of skills) {
      if (skill.package) {
        const existing = map.get(skill.package) ?? [];
        existing.push(skill);
        map.set(skill.package, existing);
      } else {
        ungrouped.push(skill);
      }
    }

    const sorted = Array.from(map.entries()).sort(([a], [b]) => a.localeCompare(b));
    if (ungrouped.length > 0) {
      sorted.push(['未分组', ungrouped]);
    }
    return sorted;
  }, [skills]);

  const defaultExpanded = useMemo(() => {
    const map: Record<string, boolean> = {};
    for (const [name] of groups) {
      map[name] = name === '未分组';
    }
    return map;
  }, [groups]);

  const [expanded, setExpanded] = useState<Record<string, boolean>>(defaultExpanded);

  // When new groups appear (e.g., after async skill loading), apply default expand/collapse
  useEffect(() => {
    setExpanded((prev) => {
      const next: Record<string, boolean> = { ...prev };
      let changed = false;
      for (const [name] of groups) {
        if (!(name in next)) {
          next[name] = name === '未分组';
          changed = true;
        }
      }
      return changed ? next : prev;
    });
  }, [groups]);

  const cycleSkill = (skillId: string) => {
    const current = skillModes[skillId] ?? 'disabled';
    onChange({ ...skillModes, [skillId]: nextMode(current) });
  };

  const toggleGroup = (_groupName: string, skillIds: string[]) => {
    const current = getGroupMode(skillModes, skillIds);
    let target: SkillMode;
    if (current === 'mixed') {
      target = 'enabled';
    } else {
      target = nextMode(current);
    }
    const updated = { ...skillModes };
    for (const id of skillIds) {
      updated[id] = target;
    }
    onChange(updated);
  };

  const toggleExpand = (groupName: string) => {
    setExpanded((prev) => ({ ...prev, [groupName]: !prev[groupName] }));
  };

  return (
    <div className="space-y-3">
      {groups.map(([groupName, groupSkills]) => {
        const skillIds = groupSkills.map((s) => s.skill_id);
        const groupMode = getGroupMode(skillModes, skillIds);
        const isExpanded = expanded[groupName] ?? false;

        return (
          <div key={groupName} className="space-y-2">
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={() => toggleGroup(groupName, skillIds)}
                className={[
                  'inline-flex items-center rounded-lg px-3 py-1.5 text-xs font-medium transition',
                  buttonClass(groupMode),
                ].join(' ')}
              >
                {groupMode === 'mixed' ? 'mixed' : groupMode}
              </button>
              <span className="text-sm font-medium text-[var(--text)]">{groupName}</span>
              <button
                type="button"
                onClick={() => toggleExpand(groupName)}
                data-testid={`chevron-${groupName}`}
                className="ml-auto text-[var(--text-secondary)] transition hover:text-[var(--text)]"
              >
                {isExpanded ? '▼' : '▶'}
              </button>
            </div>
            {isExpanded && (
              <div className="flex flex-wrap gap-2 pl-2">
                {groupSkills.map((skill) => {
                  const mode = skillModes[skill.skill_id] ?? 'disabled';
                  return (
                    <button
                      key={skill.skill_id}
                      type="button"
                      onClick={() => cycleSkill(skill.skill_id)}
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
            )}
          </div>
        );
      })}
    </div>
  );
}
