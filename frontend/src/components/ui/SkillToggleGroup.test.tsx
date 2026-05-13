import { describe, expect, it, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import SkillToggleGroup from './SkillToggleGroup';
import type { SkillItem } from '../../types';

describe('SkillToggleGroup grouping', () => {
  const skills: SkillItem[] = [
    { skill_id: 's1', label: 'Skill 1', description: null, inject_mode: 'auto', dependencies: [], package: 'aris' },
    { skill_id: 's2', label: 'Skill 2', description: null, inject_mode: 'auto', dependencies: [], package: 'aris' },
    { skill_id: 's3', label: 'Skill 3', description: null, inject_mode: 'auto', dependencies: [] },
  ];

  it('renders group headers for packaged skills', () => {
    render(
      <SkillToggleGroup
        skills={skills}
        skillModes={{}}
        onChange={vi.fn()}
      />
    );

    expect(screen.getByText('aris')).toBeInTheDocument();
    expect(screen.getByText('未分组')).toBeInTheDocument();
  });

  it('toggles all skills in a group when group toggle is clicked', () => {
    const onChange = vi.fn();
    render(
      <SkillToggleGroup
        skills={skills}
        skillModes={{ s1: 'disabled', s2: 'disabled' }}
        onChange={onChange}
      />
    );

    // Expand the aris group first (it's collapsed by default)
    const chevron = screen.getByTestId('chevron-aris');
    fireEvent.click(chevron);

    // Find the group toggle button (it's the first button in the header row)
    const arisHeader = screen.getByText('aris').parentElement;
    const groupToggle = arisHeader?.querySelector('button');
    expect(groupToggle).not.toBeNull();
    fireEvent.click(groupToggle!);

    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({ s1: 'enabled', s2: 'enabled' })
    );
  });

  it('expands and collapses groups via chevron', () => {
    render(
      <SkillToggleGroup
        skills={skills}
        skillModes={{}}
        onChange={vi.fn()}
      />
    );

    // aris group is collapsed by default — skills should not be visible
    expect(screen.queryByText('Skill 1')).not.toBeInTheDocument();

    // Click chevron to expand
    const chevron = screen.getByTestId('chevron-aris');
    fireEvent.click(chevron);

    expect(screen.getByText('Skill 1')).toBeInTheDocument();
    expect(screen.getByText('Skill 2')).toBeInTheDocument();
  });

  it('all groups are collapsed by default', () => {
    render(
      <SkillToggleGroup
        skills={skills}
        skillModes={{}}
        onChange={vi.fn()}
      />
    );

    expect(screen.queryByText('Skill 3')).not.toBeInTheDocument();
  });

  it('individual skill toggle still works inside expanded group', () => {
    const onChange = vi.fn();
    render(
      <SkillToggleGroup
        skills={skills}
        skillModes={{}}
        onChange={onChange}
      />
    );

    // Expand the ungrouped bucket first
    fireEvent.click(screen.getByTestId('chevron-未分组'));

    // Click on Skill 3 (in ungrouped)
    fireEvent.click(screen.getByText('Skill 3'));

    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({ s3: 'enabled' })
    );
  });
});
