import type { TaskStatus } from '../../types';
import { semanticToneClasses } from '../../components/ui/theme';

export const statusClassName: Record<TaskStatus, string> = {
  queued: semanticToneClasses.muted,
  starting: semanticToneClasses.info,
  running: semanticToneClasses.success,
  succeeded: semanticToneClasses.success,
  failed: semanticToneClasses.danger,
  cancelled: semanticToneClasses.warning,
  paused: semanticToneClasses.info,
};
