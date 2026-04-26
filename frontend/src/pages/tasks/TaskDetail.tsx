import type { TaskOutputEvent, TaskRecord, TaskStatus } from '../../types';

const statusLabel: Record<TaskStatus, string> = {
  queued: 'Queued',
  starting: 'Starting',
  running: 'Running',
  succeeded: 'Succeeded',
  failed: 'Failed',
};

interface TaskDetailProps {
  selectedTask: TaskRecord | null;
  detailError: string | null;
  outputItems: TaskOutputEvent[];
  outputError: string | null;
}

export default function TaskDetail({
  selectedTask,
  detailError,
  outputItems,
  outputError,
}: TaskDetailProps) {
  return (
    <section className="space-y-6 rounded-xl bg-[var(--surface)] p-6 shadow-sm">
      <div className="space-y-1">
        <h2
          className="text-lg font-semibold leading-tight tracking-[0.231px] text-[var(--text)]"
          style={{ fontFamily: 'var(--font-display)' }}
        >
          Task detail
        </h2>
        <p className="text-sm leading-relaxed tracking-[-0.224px] text-[var(--text-secondary)]">
          Detail combines binding snapshot, prompt layers, runtime payload, output replay, and
          result summary.
        </p>
      </div>

      {detailError ? <p className="text-sm text-[#ff3b30]">{detailError}</p> : null}
      {selectedTask ? (
        <div className="space-y-6">
          <section className="space-y-3 rounded-lg bg-[var(--bg-secondary)] p-4">
            <h3 className="text-xs font-semibold uppercase tracking-[0.12em] text-[var(--text-tertiary)]">
              Summary
            </h3>
            <p className="text-sm tracking-[-0.224px] text-[var(--text-secondary)]">
              <span className="font-medium text-[var(--text)]">Status:</span>{' '}
              {statusLabel[selectedTask.status]}
            </p>
            <p className="text-sm tracking-[-0.224px] text-[var(--text-secondary)]">
              <span className="font-medium text-[var(--text)]">Workspace:</span>{' '}
              {selectedTask.workspace_summary.label}
            </p>
            <p className="text-sm tracking-[-0.224px] text-[var(--text-secondary)]">
              <span className="font-medium text-[var(--text)]">Environment:</span>{' '}
              {selectedTask.environment_summary.alias} · {selectedTask.environment_summary.display_name}
            </p>
            <p className="text-sm tracking-[-0.224px] text-[var(--text-secondary)]">
              <span className="font-medium text-[var(--text)]">Latest seq:</span>{' '}
              {selectedTask.latest_output_seq}
            </p>
            {selectedTask.error_summary ? (
              <p className="text-sm text-[#ff3b30]">{selectedTask.error_summary}</p>
            ) : null}
          </section>

          <section className="space-y-3">
            <h3 className="text-xs font-semibold uppercase tracking-[0.12em] text-[var(--text-tertiary)]">
              Binding
            </h3>
            {selectedTask.binding ? (
              <div className="rounded-lg bg-[var(--bg-secondary)] p-4 text-sm tracking-[-0.224px] text-[var(--text-secondary)]">
                <p>
                  <span className="font-medium text-[var(--text)]">Resolved workdir:</span>{' '}
                  <code className="rounded bg-[var(--bg-tertiary)] px-1.5 py-0.5 text-xs">{selectedTask.binding.resolved_workdir}</code>
                </p>
                <p>
                  <span className="font-medium text-[var(--text)]">Snapshot:</span>{' '}
                  <code className="rounded bg-[var(--bg-tertiary)] px-1.5 py-0.5 text-xs">{selectedTask.binding.snapshot_path}</code>
                </p>
              </div>
            ) : (
              <p className="text-sm tracking-[-0.224px] text-[var(--text-tertiary)]">
                Binding snapshot is not available yet.
              </p>
            )}
          </section>

          <section className="space-y-3">
            <h3 className="text-xs font-semibold uppercase tracking-[0.12em] text-[var(--text-tertiary)]">
              Prompt
            </h3>
            {selectedTask.prompt ? (
              <div className="space-y-3 rounded-lg bg-[var(--bg-secondary)] p-4">
                {selectedTask.prompt.layers.map((layer) => (
                  <div key={layer.name} className="space-y-1">
                    <p className="text-sm font-medium text-[var(--text)]">
                      {layer.label}{' '}
                      <span className="text-xs text-[var(--text-tertiary)]">
                        ({layer.char_count} chars)
                      </span>
                    </p>
                    <pre className="overflow-x-auto rounded-lg bg-[var(--bg)] p-3 text-xs tracking-[-0.12px] text-[var(--text-secondary)]">
                      {layer.content}
                    </pre>
                  </div>
                ))}
              </div>
            ) : (
              <p className="text-sm tracking-[-0.224px] text-[var(--text-tertiary)]">
                Prompt manifest is not available yet.
              </p>
            )}
          </section>

          <section className="space-y-3">
            <h3 className="text-xs font-semibold uppercase tracking-[0.12em] text-[var(--text-tertiary)]">
              Runtime
            </h3>
            {selectedTask.runtime ? (
              <div className="rounded-lg bg-[var(--bg-secondary)] p-4 text-sm tracking-[-0.224px] text-[var(--text-secondary)]">
                <p>
                  <span className="font-medium text-[var(--text)]">Runner:</span>{' '}
                  {selectedTask.runtime.runner_kind ?? 'n/a'}
                </p>
                <p>
                  <span className="font-medium text-[var(--text)]">Working directory:</span>{' '}
                  <code className="rounded bg-[var(--bg-tertiary)] px-1.5 py-0.5 text-xs">{selectedTask.runtime.working_directory ?? 'n/a'}</code>
                </p>
                <p>
                  <span className="font-medium text-[var(--text)]">Command:</span>{' '}
                  <code className="rounded bg-[var(--bg-tertiary)] px-1.5 py-0.5 text-xs">{selectedTask.runtime.command.join(' ') || 'pending'}</code>
                </p>
              </div>
            ) : (
              <p className="text-sm tracking-[-0.224px] text-[var(--text-tertiary)]">
                Runtime payload is not available yet.
              </p>
            )}
          </section>

          <section className="space-y-3">
            <h3 className="text-xs font-semibold uppercase tracking-[0.12em] text-[var(--text-tertiary)]">
              Output
            </h3>
            {outputError ? <p className="text-sm text-[#ff3b30]">{outputError}</p> : null}
            <div className="max-h-[26rem] space-y-2 overflow-auto rounded-lg border border-[var(--border)] bg-[#0b1020] p-4 text-xs text-gray-100">
              {outputItems.length === 0 ? (
                <p className="text-gray-400">No output has been recorded yet.</p>
              ) : (
                outputItems.map((item) => (
                  <div key={item.seq} className="space-y-1">
                    <p className="text-[11px] uppercase tracking-[0.08em] text-gray-400">
                      #{item.seq} · {item.kind}
                    </p>
                    <pre className="whitespace-pre-wrap break-words">{item.content}</pre>
                  </div>
                ))
              )}
            </div>
          </section>

          <section className="space-y-3">
            <h3 className="text-xs font-semibold uppercase tracking-[0.12em] text-[var(--text-tertiary)]">
              Result
            </h3>
            <div className="rounded-lg bg-[var(--bg-secondary)] p-4 text-sm tracking-[-0.224px] text-[var(--text-secondary)]">
              <p>
                <span className="font-medium text-[var(--text)]">Exit code:</span>{' '}
                {selectedTask.result.exit_code ?? 'n/a'}
              </p>
              <p>
                <span className="font-medium text-[var(--text)]">Failure category:</span>{' '}
                {selectedTask.result.failure_category ?? 'n/a'}
              </p>
              <p>
                <span className="font-medium text-[var(--text)]">Completed at:</span>{' '}
                {selectedTask.result.completed_at ?? 'n/a'}
              </p>
            </div>
          </section>
        </div>
      ) : (
        <div className="rounded-lg border border-dashed border-[var(--border)] bg-[var(--bg-secondary)] p-5 text-sm tracking-[-0.224px] text-[var(--text-tertiary)]">
          Select a task from the list to inspect its persisted state.
        </div>
      )}
    </section>
  );
}
