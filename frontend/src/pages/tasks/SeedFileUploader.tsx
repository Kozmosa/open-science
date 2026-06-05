import { useCallback, useRef, useState } from 'react';
import { useT } from '../../i18n';
import { uploadFile } from '../../api/endpoints';

const MAX_SEED_FILES = 5;
const ACCEPTED_EXTENSIONS = ['.pdf', '.md'];

export interface SeedFileInfo {
    name: string;
    serverPath: string;
    size: number;
    status: 'uploading' | 'uploaded' | 'error';
    error?: string;
}

interface SeedFileUploaderProps {
    environmentId: string;
    workspaceId: string;
    disabled?: boolean;
    onFilesChange: (files: SeedFileInfo[]) => void;
}

function formatFileSize(bytes: number): string {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export default function SeedFileUploader({
    environmentId,
    workspaceId,
    disabled = false,
    onFilesChange,
}: SeedFileUploaderProps) {
    const t = useT();
    const [files, setFiles] = useState<SeedFileInfo[]>([]);
    const [isDragOver, setIsDragOver] = useState(false);
    const [errorMessage, setErrorMessage] = useState<string | null>(null);
    const inputRef = useRef<HTMLInputElement>(null);

    const notifyChange = useCallback(
        (updated: SeedFileInfo[]) => {
            onFilesChange(updated.filter((f) => f.status === 'uploaded'));
        },
        [onFilesChange],
    );

    const validateAndUpload = useCallback(
        (incoming: FileList | File[]) => {
            if (disabled) return;

            const currentCount = files.length;
            const incomingArr = Array.from(incoming);

            // Validate extensions
            const allValid = incomingArr.every((f) => {
                const ext = f.name.substring(f.name.lastIndexOf('.')).toLowerCase();
                return ACCEPTED_EXTENSIONS.includes(ext);
            });
            if (!allValid) {
                setErrorMessage(t('pages.tasks.create.seedFiles.unsupportedType'));
                return;
            }

            // Validate count
            if (currentCount + incomingArr.length > MAX_SEED_FILES) {
                setErrorMessage(t('pages.tasks.create.seedFiles.maxFilesExceeded', { max: String(MAX_SEED_FILES) }));
                return;
            }

            setErrorMessage(null);

            const newEntries: SeedFileInfo[] = incomingArr.map((f) => ({
                name: f.name,
                serverPath: `papers/${f.name}`,
                size: f.size,
                status: 'uploading' as const,
            }));

            const updated = [...files, ...newEntries];
            setFiles(updated);

            // Upload each file
            incomingArr.forEach((file, idx) => {
                const entryIndex = updated.length - incomingArr.length + idx;
                uploadFile({
                    environmentId,
                    path: `papers/${file.name}`,
                    workspaceId: workspaceId || undefined,
                    file,
                })
                    .then(() => {
                        setFiles((prev) => {
                            const next = [...prev];
                            next[entryIndex] = { ...next[entryIndex], status: 'uploaded' };
                            notifyChange(next);
                            return next;
                        });
                    })
                    .catch((err: unknown) => {
                        const msg = err instanceof Error ? err.message : String(err);
                        setFiles((prev) => {
                            const next = [...prev];
                            next[entryIndex] = { ...next[entryIndex], status: 'error', error: msg };
                            notifyChange(next);
                            return next;
                        });
                    });
            });
        },
        [disabled, files, environmentId, workspaceId, t, notifyChange],
    );

    const handleDrop = useCallback(
        (e: React.DragEvent) => {
            e.preventDefault();
            e.stopPropagation();
            setIsDragOver(false);
            if (disabled) return;
            validateAndUpload(e.dataTransfer.files);
        },
        [validateAndUpload, disabled],
    );

    const handleDragOver = useCallback(
        (e: React.DragEvent) => {
            e.preventDefault();
            e.stopPropagation();
            if (!disabled) setIsDragOver(true);
        },
        [disabled],
    );

    const handleDragLeave = useCallback((e: React.DragEvent) => {
        e.preventDefault();
        e.stopPropagation();
        setIsDragOver(false);
    }, []);

    const handleInputChange = useCallback(
        (e: React.ChangeEvent<HTMLInputElement>) => {
            if (e.target.files) {
                validateAndUpload(e.target.files);
            }
            // Reset input so the same file can be re-selected
            e.target.value = '';
        },
        [validateAndUpload],
    );

    const handleRemove = useCallback(
        (index: number) => {
            setFiles((prev) => {
                const next = prev.filter((_, i) => i !== index);
                notifyChange(next);
                return next;
            });
        },
        [notifyChange],
    );

    const handleClick = useCallback(() => {
        if (!disabled && inputRef.current) {
            inputRef.current.click();
        }
    }, [disabled]);

    return (
        <div className="space-y-2">
            <div
                role="button"
                tabIndex={disabled ? -1 : 0}
                onClick={handleClick}
                onDrop={handleDrop}
                onDragOver={handleDragOver}
                onDragEnter={handleDragOver}
                onDragLeave={handleDragLeave}
                className={[
                    'border-2 border-dashed rounded-lg p-6 text-center transition-colors',
                    disabled
                        ? 'opacity-50 pointer-events-none border-[var(--border)]'
                        : isDragOver
                            ? 'border-[var(--accent)] bg-[var(--accent-soft)] cursor-pointer'
                            : 'border-[var(--border)] cursor-pointer hover:border-[var(--accent)]',
                ].join(' ')}
            >
                <input
                    ref={inputRef}
                    type="file"
                    accept=".pdf,.md"
                    multiple
                    onChange={handleInputChange}
                    className="hidden"
                    disabled={disabled}
                />
                <p className="text-sm text-[var(--text-secondary)]">
                    {t('pages.tasks.create.seedFiles.dropzone')}
                </p>
            </div>

            {errorMessage && (
                <p className="text-xs text-[var(--danger)]">{errorMessage}</p>
            )}

            {files.length > 0 && (
                <ul className="space-y-1">
                    {files.map((file, idx) => (
                        <li
                            key={`${file.name}-${idx}`}
                            className="flex items-center justify-between py-1 px-2 text-sm rounded bg-[var(--surface-2)]"
                        >
                            <span className="truncate mr-2">
                                {file.name}
                                <span className="text-[var(--text-secondary)] ml-1">
                                    ({formatFileSize(file.size)})
                                </span>
                                {file.status === 'uploading' && (
                                    <span className="text-[var(--accent)] ml-2">
                                        {t('pages.tasks.create.seedFiles.uploading', { name: '' }).replace('...', '…')}
                                    </span>
                                )}
                                {file.status === 'error' && file.error && (
                                    <span className="text-[var(--danger)] ml-2" title={file.error}>
                                        ✗
                                    </span>
                                )}
                            </span>
                            <button
                                type="button"
                                onClick={() => handleRemove(idx)}
                                className="shrink-0 text-[var(--text-secondary)] hover:text-[var(--danger)] transition-colors"
                                aria-label={t('pages.tasks.create.seedFiles.removeFile', { name: file.name })}
                            >
                                ✕
                            </button>
                        </li>
                    ))}
                </ul>
            )}
        </div>
    );
}
