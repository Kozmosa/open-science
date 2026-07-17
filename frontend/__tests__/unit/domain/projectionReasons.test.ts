import { describe, expect, it } from 'vitest';
import { projectionReasonLabel, projectionReasonList } from '@features/domain/projectionReasons';

describe('domain projection reasons', () => {
  it('translates stable projection reason codes and legacy aliases', () => {
    expect(projectionReasonLabel('en', 'no_workspace')).toBe('No Workspace is linked to this Project.');
    expect(projectionReasonLabel('en', 'environment_grant_missing')).toBe('An active Environment grant is required.');
    expect(projectionReasonLabel('zh', 'environment_grant_required')).toBe('需要有效的环境执行授权。');
  });

  it('humanizes unknown identifiers without exposing raw snake case', () => {
    expect(projectionReasonLabel('en', 'future_runtime_requirement')).toBe('Future Runtime Requirement');
  });

  it('deduplicates projected reasons while preserving their order', () => {
    expect(projectionReasonList('en', ['failed_tasks', 'failed_tasks', 'project_archived'])).toEqual([
      'One or more Tasks need attention after failing.',
      'The linked Project is archived.',
    ]);
  });
});
