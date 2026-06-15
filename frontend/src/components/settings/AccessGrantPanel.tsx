import type { ReactNode } from 'react';
import type { AdminUserResponse } from '@/shared/types';

interface AccessGrantPanelProps {
  users: AdminUserResponse[];
  selectedUserId: string;
  onUserChange: (id: string) => void;
  onGrant: () => void;
  grantLabel: string;
  userPlaceholder: string;
  disabled?: boolean;
  extraField?: ReactNode;
}

export function AccessGrantPanel({
  users, selectedUserId, onUserChange, onGrant, grantLabel, userPlaceholder, disabled, extraField,
}: AccessGrantPanelProps) {
  const activeUsers = users.filter(u => u.status === 'active');

  return (
    <div className="flex flex-wrap gap-2 items-center p-3 rounded-lg bg-[var(--bg)] border border-dashed border-[var(--border)] mt-2">
      <select
        value={selectedUserId}
        onChange={(e) => onUserChange(e.target.value)}
        className="flex-1 min-w-[140px] text-xs px-2 py-1.5 rounded bg-[var(--surface)] border border-[var(--border)] text-[var(--text)]"
      >
        <option value="">{userPlaceholder}</option>
        {activeUsers.map((u) => (
          <option key={u.id} value={u.id}>{u.username} ({u.display_name})</option>
        ))}
      </select>
      {extraField}
      <button
        type="button"
        onClick={onGrant}
        disabled={disabled || !selectedUserId}
        className="text-xs px-3 py-1.5 bg-[var(--apple-blue)] text-white rounded disabled:opacity-40"
      >
        {grantLabel}
      </button>
    </div>
  );
}
