# Frontend Loading Optimization Design

## 目标

修复两个前端加载性能问题：Monaco 编辑器急切导入（P0）和 React Query 缓存回收缺失（P1）。

## 修复

### P0: Monaco 编辑器改为懒加载

**文件**: `frontend/src/pages/tasks/PromptEditor.tsx`

**问题**: `import Editor from '@monaco-editor/react'` 在顶层导入，导致整个 Monaco 包（74MB node_modules）被捆入 tasks 页面的 chunk，首次访问 tasks 页面时下载。

**修复**: 使用 `React.lazy()` + `Suspense` 同 `FileViewer.tsx` 一致的模式。

```tsx
import { lazy, Suspense } from 'react';
import { useMonacoTheme } from '../../hooks/useMonacoTheme';

const MonacoEditor = lazy(() => import('@monaco-editor/react'));

interface Props {
  content: string;
}

function EditorFallback() {
  return (
    <div className="border-t border-[var(--border)] flex items-center justify-center h-[300px] text-sm text-[var(--text-secondary)]">
      Loading editor...
    </div>
  );
}

export default function PromptEditor({ content }: Props) {
  const theme = useMonacoTheme();

  return (
    <div className="border-t border-[var(--border)]">
      <Suspense fallback={<EditorFallback />}>
        <MonacoEditor
          height="300px"
          language="plaintext"
          value={content}
          theme={theme}
          options={{
            readOnly: true,
            wordWrap: 'on',
            minimap: { enabled: false },
            lineNumbers: 'off',
            scrollBeyondLastLine: false,
            fontSize: 12,
            padding: { top: 12, bottom: 12 },
          }}
        />
      </Suspense>
    </div>
  );
}
```

注意：`@monaco-editor/react` 默认导出的组件名是 `Editor`，但 `lazy()` 包住后需要解构 `{ default: Editor }`。如果解构失败，用 `.then(m => ({ default: m.default }))` 处理。

### P1: React Query gcTime 配置

**文件**: `frontend/src/queryClient.ts`

**问题**: 未设置 `gcTime`，默认为 5 分钟（300000ms）。用户频繁切换页面时旧查询缓存累积占用内存。

**修复**: 添加 `gcTime: 5000` 匹配 `staleTime`，离开页面后 5 秒即回收无用的查询缓存。

```typescript
export const appQueryClientDefaultOptions = {
  queries: {
    staleTime: 5000,
    gcTime: 5000,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
  },
} satisfies DefaultOptions;
```

## 验证

1. **构建验证**: `cd frontend && npm run build` — 确认构建成功，Monaco 不再出现在页面 chunk 中
2. **类型检查**: `cd frontend && node_modules/.bin/tsc -b`
3. **功能测试**: dev server 启动后访问 tasks 页面，点击 prompt 展开 `PromptEditor`，确认编辑器正常加载
4. **Bundle 体积**: 比较修复前后的 tasks 页面 chunk 大小（预期 tasks chunk 缩小 ~74MB）
