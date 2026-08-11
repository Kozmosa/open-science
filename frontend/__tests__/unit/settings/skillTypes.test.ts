import { describe, expect, it } from 'vitest';
import { adaptSkill, parseSkillImportSource, toSkillImportRequest } from '@/features/settings/types';

describe('skill import transport types', () => {
  it('accepts only generated Skill import sources at the DOM boundary', () => {
    expect(parseSkillImportSource('git')).toBe('git');
    expect(parseSkillImportSource('local')).toBe('local');
    expect(parseSkillImportSource('remote')).toBeNull();
  });

  it('maps the generated source type into the transport request', () => {
    expect(toSkillImportRequest({
      source: 'local',
      url: null,
      localPath: '/tmp/example-skill',
      skillId: null,
    })).toEqual({
      source: 'local',
      url: null,
      local_path: '/tmp/example-skill',
      skill_id: null,
    });
  });

  it('preserves the generated Skill inject mode', () => {
    expect(adaptSkill({
      skill_id: 'paper-reading',
      label: 'Paper Reading',
      inject_mode: 'disabled',
    }).inject_mode).toBe('disabled');
    expect(adaptSkill({
      skill_id: 'default-skill',
      label: 'Default Skill',
    }).inject_mode).toBe('auto');
  });
});
