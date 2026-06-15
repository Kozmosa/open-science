import { useEffect, useMemo, useState } from 'react';
import { semanticToneClasses } from '@design-system/tokens/theme';
import { useT } from '@/shared/i18n';
import type { SkillItem } from '@/shared/types';

interface Props {
  skills: SkillItem[];
  selectedSkillIds: string[];
  onChange: (skillIds: string[]) => void;
}

function groupSkills(skills: SkillItem[], ungroupedLabel: string): Array<[string, SkillItem[]]> {
  const grouped = new Map<string, SkillItem[]>();
  const ungrouped: SkillItem[] = [];

  for (const skill of skills) {
    if (skill.package) {
      const bucket = grouped.get(skill.package) ?? [];
      bucket.push(skill);
      grouped.set(skill.package, bucket);
    } else {
      ungrouped.push(skill);
    }
  }

  const groups = Array.from(grouped.entries()).sort(([left], [right]) => left.localeCompare(right));
  if (ungrouped.length > 0) {
    groups.push([ungroupedLabel, ungrouped]);
  }
  return groups.map(([name, group]) => [
    name,
    [...group].sort((left, right) => left.label.localeCompare(right.label)),
  ]);
}

export default function TaskSkillPicker({ skills, selectedSkillIds, onChange }: Props) {
  const t = useT();
  const groups = useMemo(() => groupSkills(skills, t('components.skills.ungrouped')), [skills, t]);
  const selectedSet = useMemo(() => new Set(selectedSkillIds), [selectedSkillIds]);
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setExpanded((current) => {
      let changed = false;
      const next = { ...current };
      for (const [groupName] of groups) {
        if (!(groupName in next)) {
          next[groupName] = false;
          changed = true;
        }
      }
      return changed ? next : current;
    });
  }, [groups]);

  const updateSelected = (nextSelected: Set<string>) => {
    onChange(skills.filter((skill) => nextSelected.has(skill.skill_id)).map((skill) => skill.skill_id));
  };

  const toggleSkill = (skillId: string) => {
    const next = new Set(selectedSet);
    if (next.has(skillId)) {
      next.delete(skillId);
    } else {
      next.add(skillId);
    }
    updateSelected(next);
  };

  const toggleGroup = (groupSkills: SkillItem[]) => {
    const next = new Set(selectedSet);
    const allSelected = groupSkills.every((skill) => next.has(skill.skill_id));
    for (const skill of groupSkills) {
      if (allSelected) {
        next.delete(skill.skill_id);
      } else {
        next.add(skill.skill_id);
      }
    }
    updateSelected(next);
  };

  if (skills.length === 0) {
    return (
      <p className="rounded-lg border border-[var(--border)] bg-[var(--bg-secondary)] px-3 py-2 text-xs text-[var(--text-secondary)]">
        {t('pages.tasks.create.noSkillsAvailable')}
      </p>
    );
  }

  return (
    <div className="space-y-3" aria-label={t('pages.tasks.skillsLabel')}>
      {groups.map(([groupName, groupSkills]) => {
        const selectedCount = groupSkills.filter((skill) => selectedSet.has(skill.skill_id)).length;
        const isExpanded = expanded[groupName] ?? false;
        const allSelected = selectedCount === groupSkills.length && groupSkills.length > 0;
        const hasSelection = selectedCount > 0;

        return (
          <section key={groupName} className="rounded-xl border border-[var(--border)] bg-[var(--surface)] p-3">
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={() => toggleGroup(groupSkills)}
                aria-pressed={allSelected}
                className={[
                  'inline-flex shrink-0 items-center rounded-lg border px-3 py-1.5 text-xs font-medium transition hover:opacity-85',
                  hasSelection ? semanticToneClasses.info : semanticToneClasses.muted,
                ].join(' ')}
              >
                {t('pages.tasks.create.skillGroupSelected', {
                  selected: selectedCount,
                  total: groupSkills.length,
                })}
              </button>
              <span className="min-w-0 truncate text-sm font-medium text-[var(--text)]" title={groupName}>{groupName}</span>
              <button
                type="button"
                onClick={() => setExpanded((current) => ({ ...current, [groupName]: !isExpanded }))}
                aria-expanded={isExpanded}
                aria-label={isExpanded
                  ? t('pages.tasks.create.hideSkillGroup', { group: groupName })
                  : t('pages.tasks.create.showSkillGroup', { group: groupName })}
                className="ml-auto rounded-md px-2 py-1 text-[var(--text-secondary)] transition hover:bg-[var(--bg-secondary)] hover:text-[var(--text)]"
              >
                {isExpanded ? '▼' : '▶'}
              </button>
            </div>
            {isExpanded ? (
              <div className="mt-3 flex flex-wrap gap-2">
                {groupSkills.map((skill) => {
                  const selected = selectedSet.has(skill.skill_id);
                  return (
                    <button
                      key={skill.skill_id}
                      type="button"
                      onClick={() => toggleSkill(skill.skill_id)}
                      aria-pressed={selected}
                      aria-label={selected
                        ? t('pages.tasks.create.deselectSkill', { skill: skill.label })
                        : t('pages.tasks.create.selectSkill', { skill: skill.label })}
                      title={skill.description ?? skill.label}
                      className={[
                        'inline-flex items-center rounded-full border px-3 py-1.5 text-xs font-medium transition hover:opacity-85',
                        selected ? semanticToneClasses.info : semanticToneClasses.muted,
                      ].join(' ')}
                    >
                      {skill.label}
                    </button>
                  );
                })}
              </div>
            ) : null}
          </section>
        );
      })}
      <p className="text-xs text-[var(--text-tertiary)]">{t('pages.tasks.skillDependenciesHint')}</p>
    </div>
  );
}
