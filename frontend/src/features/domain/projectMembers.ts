import type { DomainProjectMember } from './types';

export type DomainProjectMemberRole = DomainProjectMember['role'];

export function parseDomainProjectMemberRole(value: string): DomainProjectMemberRole | null {
  return value === 'editor' || value === 'viewer' ? value : null;
}
