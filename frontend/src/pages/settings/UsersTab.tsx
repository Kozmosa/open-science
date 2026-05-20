import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { getAdminUsers, updateAdminUser, resetUserPassword } from '../../api';
import { useAuth } from '../../contexts/AuthContext';

export function UsersTab() {
  const { user: currentUser } = useAuth();
  const queryClient = useQueryClient();
  const [resetUserId, setResetUserId] = useState<string | null>(null);
  const [newPassword, setNewPassword] = useState('');

  const { data, isLoading } = useQuery({
    queryKey: ['admin', 'users'],
    queryFn: getAdminUsers,
    enabled: currentUser?.role === 'admin',
  });

  const updateMutation = useMutation({
    mutationFn: ({ id, status }: { id: string; status: string }) =>
      updateAdminUser(id, { status }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['admin', 'users'] }),
  });

  const resetMutation = useMutation({
    mutationFn: ({ id, password }: { id: string; password: string }) =>
      resetUserPassword(id, { password }),
    onSuccess: () => { setResetUserId(null); setNewPassword(''); },
  });

  if (currentUser?.role !== 'admin') return null;
  if (isLoading) return <p className="text-sm text-gray-400 p-4">Loading...</p>;

  const users = data?.items ?? [];

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold">Users</h3>
        <span className="text-xs text-gray-500">{users.length} users</span>
      </div>
      {users.map((u) => (
        <div key={u.id} className={`flex items-center justify-between p-3 rounded-lg border text-sm ${
          u.status === 'pending' ? 'bg-yellow-50 border-yellow-200' :
          u.status === 'active' ? 'bg-green-50 border-green-200' : 'bg-gray-50 border-gray-200'
        }`}>
          <div>
            <span className="font-medium">{u.username}</span>
            <span className="text-gray-400 ml-2">{u.display_name}</span>
            <span className={`ml-2 text-xs px-1.5 py-0.5 rounded ${
              u.status === 'pending' ? 'bg-yellow-100 text-yellow-800' :
              u.status === 'active' ? 'bg-green-100 text-green-800' : 'bg-gray-200 text-gray-600'
            }`}>{u.status}</span>
            {u.role === 'admin' && <span className="ml-1 text-xs bg-blue-100 text-blue-800 px-1.5 py-0.5 rounded">admin</span>}
          </div>
          <div className="flex gap-2">
            {u.status === 'pending' && (
              <button type="button" onClick={() => updateMutation.mutate({ id: u.id, status: 'active' })}
                className="text-xs px-2 py-1 bg-green-600 text-white rounded hover:bg-green-700">Approve</button>
            )}
            {u.status === 'active' && u.id !== currentUser.id && (
              <button type="button" onClick={() => updateMutation.mutate({ id: u.id, status: 'disabled' })}
                className="text-xs px-2 py-1 bg-gray-200 rounded hover:bg-gray-300">Disable</button>
            )}
            {u.status === 'disabled' && (
              <button type="button" onClick={() => updateMutation.mutate({ id: u.id, status: 'active' })}
                className="text-xs px-2 py-1 bg-green-600 text-white rounded hover:bg-green-700">Re-enable</button>
            )}
            {u.id !== currentUser.id && (
              <button type="button" onClick={() => setResetUserId(resetUserId === u.id ? null : u.id)}
                className="text-xs px-2 py-1 bg-gray-200 rounded hover:bg-gray-300">Reset PW</button>
            )}
          </div>
        </div>
      ))}
      {resetUserId && (
        <div className="flex gap-2 items-center p-3 bg-blue-50 rounded-lg border border-blue-200">
          <span className="text-xs text-gray-600">New password:</span>
          <input
            type="text"
            value={newPassword}
            onChange={(e) => setNewPassword(e.target.value)}
            placeholder="Enter new password"
            className="text-xs px-2 py-1 border rounded flex-1"
          />
          <button
            type="button"
            onClick={() => resetMutation.mutate({ id: resetUserId, password: newPassword })}
            disabled={!newPassword}
            className="text-xs px-2 py-1 bg-blue-600 text-white rounded disabled:opacity-50"
          >Set</button>
        </div>
      )}
    </div>
  );
}
