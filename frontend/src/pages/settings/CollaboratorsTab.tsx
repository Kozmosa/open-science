import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { getProjects, getCollaborators, addCollaborator, removeCollaborator, getAdminUsers } from '../../api';
import { useAuth } from '../../contexts/AuthContext';

export function CollaboratorsTab() {
  const { user } = useAuth();
  const queryClient = useQueryClient();
  const [selectedProject, setSelectedProject] = useState<string | null>(null);
  const [addUserId, setAddUserId] = useState('');
  const [addRole, setAddRole] = useState('member');

  const { data: projects } = useQuery({ queryKey: ['projects'], queryFn: () => getProjects() });
  const { data: allUsers } = useQuery({
    queryKey: ['admin', 'users'], queryFn: getAdminUsers, enabled: user?.role === 'admin',
  });
  const { data: collabs } = useQuery({
    queryKey: ['collaborators', selectedProject],
    queryFn: () => getCollaborators(selectedProject!),
    enabled: !!selectedProject,
  });
  const addMutation = useMutation({
    mutationFn: () => addCollaborator(selectedProject!, { user_id: addUserId, role: addRole }),
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ['collaborators', selectedProject] }); setAddUserId(''); },
  });
  const removeMutation = useMutation({
    mutationFn: (userId: string) => removeCollaborator(selectedProject!, userId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['collaborators', selectedProject] }),
  });

  const projectList = projects?.items ?? [];

  return (
    <div className="flex flex-col gap-4">
      <h3 className="text-sm font-semibold">Project Collaborators</h3>
      <select value={selectedProject ?? ''} onChange={(e) => setSelectedProject(e.target.value || null)}
        className="text-sm px-3 py-2 rounded-lg bg-[var(--bg)] border border-[var(--border)]">
        <option value="">Select project...</option>
        {projectList.map((p) => <option key={p.project_id} value={p.project_id}>{p.name}</option>)}
      </select>
      {selectedProject && (
        <div className="flex flex-col gap-2">
          {(collabs?.items ?? []).map((c) => (
            <div key={c.user_id} className="flex items-center justify-between p-3 rounded-lg bg-[var(--bg)] border border-[var(--border)] text-sm">
              <div><span className="font-medium">{c.username}</span><span className="text-[var(--text-secondary)] ml-2">{c.display_name}</span></div>
              <div className="flex items-center gap-2">
                <span className="text-xs text-[var(--text-secondary)] capitalize">{c.role}</span>
                <button type="button" onClick={() => removeMutation.mutate(c.user_id)} className="text-xs text-red-500 hover:text-red-700">Remove</button>
              </div>
            </div>
          ))}
          <div className="flex gap-2 items-center p-3 rounded-lg bg-[var(--bg)] border border-dashed border-[var(--border)] mt-2">
            <select value={addUserId} onChange={(e) => setAddUserId(e.target.value)}
              className="flex-1 text-xs px-2 py-1.5 rounded bg-[var(--surface)] border border-[var(--border)]">
              <option value="">Add user...</option>
              {(allUsers?.items ?? []).filter(u => u.status === 'active').map((u) => (
                <option key={u.id} value={u.id}>{u.username} ({u.display_name})</option>
              ))}
            </select>
            <select value={addRole} onChange={(e) => setAddRole(e.target.value)}
              className="text-xs px-2 py-1.5 rounded bg-[var(--surface)] border border-[var(--border)]">
              <option value="member">member</option>
              <option value="viewer">viewer</option>
            </select>
            <button type="button" onClick={() => addMutation.mutate()} disabled={!addUserId}
              className="text-xs px-3 py-1.5 bg-blue-600 text-white rounded disabled:opacity-50">Add</button>
          </div>
        </div>
      )}
    </div>
  );
}
