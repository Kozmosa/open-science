import { describe, expect, it } from 'vitest';

import { parseDomainProjectMemberRole } from './projectMembers';

describe('parseDomainProjectMemberRole', () => {
  it('accepts the canonical project member roles', () => {
    expect(parseDomainProjectMemberRole('editor')).toBe('editor');
    expect(parseDomainProjectMemberRole('viewer')).toBe('viewer');
  });

  it('rejects legacy and unknown role values', () => {
    expect(parseDomainProjectMemberRole('member')).toBeNull();
    expect(parseDomainProjectMemberRole('owner')).toBeNull();
    expect(parseDomainProjectMemberRole('')).toBeNull();
  });
});
