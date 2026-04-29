import { useState, useCallback } from 'react';
import { ChevronDown, ChevronRight, File, Folder, FolderOpen } from 'lucide-react';
import type { FileEntry } from '../../types';

interface FileTreeProps {
  entries: FileEntry[];
  selectedPath: string | null;
  onSelectFile: (path: string) => void;
  onLoadDirectory: (path: string) => Promise<FileEntry[]>;
}

interface TreeNodeProps {
  entry: FileEntry;
  selectedPath: string | null;
  onSelectFile: (path: string) => void;
  onLoadDirectory: (path: string) => Promise<FileEntry[]>;
}

function TreeNode({ entry, selectedPath, onSelectFile, onLoadDirectory }: TreeNodeProps) {
  const [expanded, setExpanded] = useState(false);
  const [children, setChildren] = useState<FileEntry[] | null>(null);
  const [loading, setLoading] = useState(false);
  const isSelected = selectedPath === entry.path;

  const handleToggle = useCallback(async () => {
    if (entry.kind !== 'directory') {
      onSelectFile(entry.path);
      return;
    }
    if (!expanded) {
      if (children === null) {
        setLoading(true);
        try {
          const loaded = await onLoadDirectory(entry.path);
          setChildren(loaded);
        } catch {
          setChildren([]);
        } finally {
          setLoading(false);
        }
      }
      setExpanded(true);
    } else {
      setExpanded(false);
    }
  }, [expanded, children, entry, onLoadDirectory, onSelectFile]);

  const handleSelect = useCallback(() => {
    onSelectFile(entry.path);
  }, [entry.path, onSelectFile]);

  return (
    <div>
      <button
        type="button"
        onClick={entry.kind === 'directory' ? handleToggle : handleSelect}
        className={`flex w-full items-center gap-1.5 rounded px-2 py-1 text-left text-sm transition ${
          isSelected
            ? 'bg-[var(--apple-blue)]/10 text-[var(--apple-blue)]'
            : 'text-[var(--text)] hover:bg-[var(--bg-secondary)]'
        }`}
      >
        {entry.kind === 'directory' ? (
          expanded ? (
            <ChevronDown className="h-3.5 w-3.5 shrink-0 text-[var(--text-tertiary)]" />
          ) : (
            <ChevronRight className="h-3.5 w-3.5 shrink-0 text-[var(--text-tertiary)]" />
          )
        ) : (
          <span className="w-3.5 shrink-0" />
        )}
        {entry.kind === 'directory' ? (
          expanded ? (
            <FolderOpen className="h-4 w-4 shrink-0 text-[var(--apple-blue)]" />
          ) : (
            <Folder className="h-4 w-4 shrink-0 text-[var(--text-tertiary)]" />
          )
        ) : (
          <File className="h-4 w-4 shrink-0 text-[var(--text-tertiary)]" />
        )}
        <span className="truncate">{entry.name}</span>
      </button>
      {entry.kind === 'directory' && expanded && (
        <div className="ml-4 border-l border-[var(--border)] pl-1">
          {loading ? (
            <p className="px-2 py-1 text-xs text-[var(--text-tertiary)]">Loading...</p>
          ) : children && children.length > 0 ? (
            children.map((child) => (
              <TreeNode
                key={child.path}
                entry={child}
                selectedPath={selectedPath}
                onSelectFile={onSelectFile}
                onLoadDirectory={onLoadDirectory}
              />
            ))
          ) : (
            <p className="px-2 py-1 text-xs text-[var(--text-tertiary)]">Empty directory</p>
          )}
        </div>
      )}
    </div>
  );
}

export default function FileTree({ entries, selectedPath, onSelectFile, onLoadDirectory }: FileTreeProps) {
  if (entries.length === 0) {
    return <p className="px-3 py-2 text-sm text-[var(--text-tertiary)]">No files</p>;
  }

  return (
    <div className="space-y-0.5">
      {entries.map((entry) => (
        <TreeNode
          key={entry.path}
          entry={entry}
          selectedPath={selectedPath}
          onSelectFile={onSelectFile}
          onLoadDirectory={onLoadDirectory}
        />
      ))}
    </div>
  );
}
