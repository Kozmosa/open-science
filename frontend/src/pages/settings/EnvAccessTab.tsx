import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { getEnvironments, getEnvAccess, grantEnvAccess, revokeEnvAccess, getAdminUsers } from '../../api';
import { useAuth } from '../../contexts/AuthContext';

export function EnvAccessTab() {
  const { user } = useAuth();
  const queryClient = useQueryClient();
  const [selectedEnv, setSelectedEnv] = useState<string | null>(null);
  const [grantUserId, setGrantUserId] = useState('');
  const [maxTasks, setMaxTasks] = useState('');

  const { data: envs } = useQuery({
    queryKey: ['environments'],
    queryFn: () => getEnvironments(),
    enabled: user?.role === 'admin',
  });
  const { data: users } = useQuery({
    queryKey: ['admin', 'users'],
    queryFn: getAdminUsers,
    enabled: user?.role === 'admin',
  });
  const { data: accessData } = useQuery({
    queryKey: ['envAccess', selectedEnv],
    queryFn: () => getEnvAccess(selectedEnv!),
    enabled: !!selectedEnv && user?.role === 'admin',
  });

  const grantMutation = useMutation({
    mutationFn: () => grantEnvAccess(selectedEnv!, { user_id: grantUserId, max_concurrent_tasks: maxTasks ? parseInt(maxTasks) : null }),
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ['envAccess', selectedEnv] }); setGrantUserId(''); setMaxTasks(''); },
  });

  const revokeMutation = useMutation({
    mutationFn: (userId: string) => revokeEnvAccess(selectedEnv!, userId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['envAccess', selectedEnv] }),
  });

  if (user?.role !== 'admin') return null;

  return (
    <div className="flex flex-col gap-4">
      <h3 className="text-sm font-semibold">Environment Access</h3>
      <select
        value={selectedEnv ?? ''}
        onChange={(e) => setSelectedEnv(e.target.value || null)}
        className="text-sm px-2 py-1.5 border rounded-lg"
      >
        <option value="">Select environment...</option>
        {(envs?.items ?? []).map((e) => (
          <option key={e.id} value={e.id}>{e.display_name || e.alias}</option>
        ))}
      </select>

      {selectedEnv && (
        <div className="flex flex-col gap-2">
          {(accessData?.items ?? []).map((a) => (
            <div key={a.user_id} className="flex items-center justify-between p-2 bg-gray-50 rounded-lg text-sm">
              <div>
                <span className="font-medium">{a.username}</span>
                <span className="text-gray-400 ml-2">{a.display_name}</span>
              </div>
              <div className="flex items-center gap-3">
                <span className="text-xs text-gray-500">Max tasks: {a.max_concurrent_tasks ?? 'unlimited'}</span>
                <button
                  type="button"
                  onClick={() => revokeMutation.mutate(a.user_id)}
                  className="text-xs text-red-600 hover:text-red-800"
                >Remove</button>
              </div>
            </div>
          ))}

          <div className="flex gap-2 items-center p-3 bg-blue-50 rounded-lg border border-blue-200 mt-2">
            <select
              value={grantUserId}
              onChange={(e) => setGrantUserId(e.target.value)}
              className="text-xs px-2 py-1 border rounded"
            >
              <option value="">Grant to...</option>
              {(users?.items ?? []).filter(u => u.status === 'active').map((u) => (
                <option key={u.id} value={u.id}>{u.username} ({u.display_name})</option>
              ))}
            </select>
            <input
              value={maxTasks}
              onChange={(e) => setMaxTasks(e.target.value)}
              placeholder="Max tasks"
              className="text-xs px-2 py-1 border rounded w-24"
            />
            <button
              type="button"
              onClick={() => grantMutation.mutate()}
              disabled={!grantUserId}
              className="text-xs px-2 py-1 bg-blue-600 text-white rounded disabled:opacity-50"
            >Grant</button>
          </div>
        </div>
      )}
    </div>
  );
}
