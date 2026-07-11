# osci 设计系统与设计语言

**Status:** Accepted architecture — token 分层、主题扩展、shadcn 采用方式、字体优先级和渐进迁移边界已确认
**Date:** 2026-07-11
**Scope:** OpenScience WebUI 的视觉基础、主题契约、CSS 命名、字体、组件状态、第三方主题边界与组件来源策略
**Related:** 产品信息架构、全局外壳和页面原型见 [`2026-07-11-openscience-console-design.md`](2026-07-11-openscience-console-design.md)

## 1. 结论

`osci` 是 OpenScience 的正式设计系统命名空间。它不是一套单独发布的 UI 框架，也不等同于 shadcn/ui。它负责定义 OpenScience 的稳定视觉与交互契约，业务页面只能通过这个契约使用共享样式和组件。

核心决策如下：

1. 使用三层 token：基础色板、语义 token、少量组件 token。
2. 浅色和深色是两套独立设计的官方主题，不通过自动反色生成。
3. 主题选择只改变语义 token；业务组件不直接判断主题名称。
4. 允许未来增加官方配色和受控第三方主题，但不允许主题执行 JavaScript 或注入任意 CSS。
5. 通用组件的目标状态统一收敛到 shadcn/ui 衍生实现；OpenScience 特有布局和复杂工作面继续自研。迁移按组件族渐进完成，不把 shadcn CLI 或目录约定变成运行时依赖。
6. 拉丁字符使用本地托管的 Noto Sans WOFF2，提供 400、500、600、700 四个静态字重；中文使用系统中文字体并继承相同字重。系统 UI 字体栈是可靠回退。字体来源、OFL 许可和文件哈希必须随仓库记录。
7. 所有新增自定义 CSS token、全局类和数据属性使用 `osci` 命名空间。

## 2. 设计语言

OpenScience 的界面应表现为安静、精确、开放的研究工作台：

- **安静**：不依靠大面积装饰色、强阴影或持续动画争夺注意力。
- **精确**：状态、时间、来源和动作结果清楚可辨，不能用模糊文案掩盖不确定性。
- **开放**：页面结构允许用户从文献、任务、项目和工作区继续深入，而不是被封闭的仪表盘困住。
- **高效**：默认信息密度适合桌面研究工作，常用动作不隐藏在多级菜单中。
- **连贯**：同一种状态、按钮层级和页面结构在不同功能中保持一致。

## 3. 命名与目录边界

### 3.1 CSS 命名

- 自定义属性：`--osci-*`，例如 `--osci-color-primary`。
- 自定义全局类：`osci-*`，例如 `osci-topbar`。
- 数据属性：`data-osci-*`，例如 `data-osci-theme="light"`。
- 本地存储：`openscience:*`；用户级偏好必须包含稳定用户 ID。

Tailwind 工具类、第三方库类名、CSS module 局部类和 React 组件名不添加前缀。

### 3.2 建议目录

```text
frontend/src/design-system/
  tokens/
    palette.css
    semantic.css
    component.css
    themes/
      osci-light.css
      osci-dark.css
  primitives/
  patterns/
  hooks/
  theme/
    contract.ts
    registry.ts
    validator.ts
```

现有目录允许渐进迁移到该结构，不进行一次性移动。业务功能只能从 `@design-system` 公共入口导入共享组件，不直接引用主题实现文件或底层交互库。

## 4. Token 分层

### 4.1 基础色板

基础色板保存无业务含义的颜色阶梯，例如 blue、neutral、green、amber 和 red。业务组件不得直接使用色板 token；色板只用于定义主题的语义 token。

### 4.2 语义 token

语义 token 描述用途而不是具体颜色。首版至少包含：

```text
--osci-color-canvas
--osci-color-surface
--osci-color-surface-subtle
--osci-color-surface-elevated
--osci-color-text
--osci-color-text-secondary
--osci-color-text-muted
--osci-color-border-subtle
--osci-color-border
--osci-color-border-strong
--osci-color-primary
--osci-color-primary-hover
--osci-color-primary-soft
--osci-color-focus
--osci-color-success
--osci-color-warning
--osci-color-danger
--osci-color-info
--osci-shadow-sm
--osci-shadow-md
--osci-shadow-overlay
--osci-radius-sm
--osci-radius-md
--osci-radius-lg
--osci-font-ui
--osci-font-display
--osci-font-mono
```

业务组件只消费这一层。现有 `--prism-*`、`--apple-*`、`--surface`、`--text` 等变量作为兼容别名逐步指向新的语义 token。

### 4.3 组件 token

只有无法由通用语义 token 清楚表达的稳定组件属性才进入组件层，例如：

```text
--osci-topbar-background
--osci-topbar-backdrop-filter
--osci-command-palette-width
--osci-sidebar-expanded-width
--osci-sidebar-collapsed-width
```

不要为每个组件的每个内距建立 token，也不要让组件 token 复制完整色板。

## 5. 官方主题

### 5.1 浅色主题基线

| 用途 | 建议值 |
| --- | --- |
| Canvas / Surface | `#ffffff` |
| Subtle surface | `#f5f5f7` |
| Primary text | `#1d1d1f` |
| Secondary text | `#515154` |
| Muted text | `#6e6e73` |
| Subtle border | `rgba(29, 29, 31, 0.08)` |
| Border | `rgba(29, 29, 31, 0.14)` |
| Strong border | `rgba(29, 29, 31, 0.22)` |
| OpenScience blue | `#2563eb` |
| Primary hover | `#1d4ed8` |
| Primary soft | `rgba(37, 99, 235, 0.08)` |
| Success | `#15803d` |
| Warning | `#b45309` |
| Danger | `#dc2626` |

页面画布保持纯白。`#f5f5f7` 只用于局部次级表面、状态提示和输入区域，不能重新形成整页灰色内容面。

### 5.2 深色主题基线

| 用途 | 建议值 |
| --- | --- |
| Canvas | `#0f0f10` |
| Surface | `#1d1d1f` |
| Subtle surface | `#242426` |
| Elevated surface | `#2c2c2e` |
| Primary text | `#f5f5f7` |
| Secondary text | `#d2d2d7` |
| Muted text | `#a1a1aa` |
| Subtle border | `rgba(255, 255, 255, 0.08)` |
| Border | `rgba(255, 255, 255, 0.14)` |
| Strong border | `rgba(255, 255, 255, 0.22)` |
| OpenScience blue | `#60a5fa` |
| Primary hover | `#93c5fd` |
| Primary soft | `rgba(96, 165, 250, 0.12)` |
| Success | `#4ade80` |
| Warning | `#fbbf24` |
| Danger | `#f87171` |

深色主题是独立验收对象。不能因为浅色主题通过，就认为替换几个背景色后深色主题自动成立。

### 5.3 主题应用

根节点通过 `data-osci-theme` 选择主题：

```html
<html data-osci-theme="light">
```

组件不得读取 `light`、`dark` 或第三方主题 ID 决定颜色。它们只使用语义 token。`color-scheme` 与主题同步，使原生表单和滚动条采用正确模式。

官方主题支持 `light`、`dark` 和 `system` 偏好，并在第一批设置界面中开放选择；默认值为 `light`。主题偏好通过版本化 WebUI 设置保存，迁移逻辑与组件实现解耦。

Terminal 是允许保持专用深色表面的工具；Monaco 和普通 Markdown 代码块跟随应用主题。

## 6. 第三方主题契约

第三方主题使用版本化数据契约，不接受任意 CSS 文件：

```ts
interface OsciThemeManifestV1 {
  contract: 'osci-theme/v1';
  id: string;
  name: string;
  mode: 'light' | 'dark';
  author?: string;
  tokens: Record<OsciThemeTokenName, string>;
}
```

加载时必须：

1. 校验主题 ID、契约版本和 token allowlist；
2. 拒绝 `url()`、脚本、任意 selector 和未知 token；
3. 校验颜色、长度、阴影等值的允许格式；
4. 检查文字/背景、焦点和状态颜色的最低对比度；
5. 无效主题回退到对应模式的官方主题。

首版只完成第三方主题底层契约、格式、验证器和测试，不提供导入界面或在线主题市场。未来的第三方主题先作为管理员安装或本地导入的纯数据文件，避免把远程样式执行面引入产品。

## 7. 字体

### 7.1 优先级

UI 字体顺序：

1. 拉丁字符使用本地托管的 `Noto Sans osci` WOFF2，包含 400、500、600、700 字重；
2. 中文使用系统中文字体，并按组件声明使用对应字重；
3. 字体资产缺失时整体回退到系统 UI 字体栈。

建议字体栈：

```css
font-family:
  "Noto Sans osci",
  -apple-system,
  BlinkMacSystemFont,
  "Segoe UI",
  "PingFang SC",
  "Microsoft YaHei",
  "Noto Sans CJK SC",
  sans-serif;
```

Noto Sans 文件只包含拉丁字符，并通过 `unicode-range` 限定使用范围；中文自动落到系统中文字体。字体使用 `font-display: swap`。正文采用 400，常规控件采用 500，区块与工作页标题采用 600，仅在确有强调需要时使用 700。全局禁用未声明字重的字体合成。

### 7.2 许可与托管

字体不得把 jsDelivr、Google Fonts 或其他公共 CDN 作为产品运行时的必要依赖。实施时从 Noto 官方来源生成或下载仅含所需拉丁字符的 400、500、600、700 WOFF2，并由前端静态资产托管，同时在仓库中记录：

- 官方来源 URL；
- 下载版本和文件哈希；
- 对应许可或使用条款；
- 字重与字符子集。

Noto Sans 字体资产必须附带 SIL Open Font License 文本。若构建时字体资产缺失或校验失败，产品自动回退到系统 UI 字体栈，不发起外部字体请求。

等宽字体使用本地托管且许可明确的 JetBrains Mono，或使用系统等宽字体回退。

## 8. 尺寸、间距和排版

- 基础间距单位：4px。
- 常用页面内距：12px、16px、24px；同一页面原型不得随意混用。
- 小/中/大圆角：8px、12px、16px；胶囊标签使用完整圆角。
- 正文：14px / 1.5。
- 辅助文字：12px / 1.4，必须满足对比度要求。
- 工作页标题：24px、600 字重。
- 区块标题：16px、600 字重。
- TopBar：桌面端 48px。

紧凑组件必须保留至少 32px 的鼠标点击高度；面向窄屏的主要触控目标至少 44px。

## 9. 组件状态契约

所有交互组件必须明确支持：

- default；
- hover；
- active/pressed；
- focus-visible；
- disabled；
- loading（适用时）；
- error/invalid（表单组件）；
- selected/current（导航与选择组件）。

Focus 不允许只靠颜色变化，默认使用 2px 的 `--osci-color-focus` 外圈。Loading 状态必须防止重复提交，并保留按钮宽度。Disabled 状态不能仅降低到不可读的透明度。

## 10. shadcn/ui 采用策略

### 10.1 采用结论

OpenScience 采用 shadcn/ui 的“源码归项目所有”模式与成熟组件结构。最终目标是：凡 shadcn 能稳定覆盖的通用 primitive 和 overlay 组件，都迁移到经过 `osci` 适配的 shadcn 衍生实现；不再长期维护两套同类基础组件。

当前项目已经具备 CVA、`clsx`、`tailwind-merge`、Lucide、Tailwind 和自有 primitives，与 shadcn 的基础结构高度重合，因此迁移的重点是统一组件契约和交互质量，而不是引入另一套并行 UI 系统。

目标组件范围包括 Button、Input、Textarea、Select、Checkbox、Radio、Switch、Badge、Alert、Card、Dialog、Sheet、Dropdown Menu、Popover、Tooltip、Tabs、Command、Toast、Form 等通用组件。PageShell、SplitPane、CardGrid、ProjectCanvas、任务流、Terminal 和 Monaco 等 OpenScience 特有工作面继续由项目维护，但只能消费 `osci` token 和基础组件。

### 10.2 使用边界

- shadcn CLI 只作为生成和参考工具，不是运行时依赖。
- 生成组件进入 `frontend/src/design-system/`，经过 `osci` token、文案、测试和公共 API 适配后才能使用。
- 业务代码只能从 `@design-system` 导入，不直接从 `@radix-ui/*` 或临时 `components/ui` 路径导入。
- Radix 等底层库用于需要焦点管理、弹层定位、键盘导航或复杂选择行为的组件；简单展示组件保持轻量实现。
- 现有同类基础组件最终都要收敛，但按组件族渐进迁移：先建立新组件和兼容 API，再迁移调用方、运行验证，最后删除旧实现。禁止一次提交同时替换全部组件和页面。
- shadcn 上游更新由人工审查后合入，不能用 CLI 覆盖本地已适配组件。

Command Palette 是首个适合使用 shadcn Command 风格与成熟无障碍底层的组件。第一迁移批次包括 Dialog/Modal、Dropdown Menu、Popover、Tooltip、Select 和 Toast；第二批迁移 Button、表单控件、Card、Badge 和 Alert；页面级 OpenScience 组件最后按使用面收敛。

## 11. 可访问性与主题质量门禁

- 正文和辅助文字满足 WCAG AA 对比度；大字号之外不使用低于 4.5:1 的文字颜色。
- 所有主题必须验证 focus-visible、选中态、错误态和 disabled 状态。
- 模糊表面必须有实色回退，并在 reduced transparency 或性能降级模式下保持可读。
- 主题切换不得导致布局尺寸变化、组件重挂载或业务状态丢失。
- 组件测试至少覆盖键盘路径、ARIA 名称、Escape/焦点恢复和主题无关的行为契约。

可拖拽概览卡片的排序是可选个性化能力。首期只支持指针拖拽，不支持键盘重排；键盘用户仍能按稳定顺序访问全部内容和操作，因此不影响核心功能可达性。

## 12. 渐进迁移

1. 建立 `osci` token、浅色/深色官方主题和旧变量兼容别名。
2. 将全局外壳、TopBar、侧栏、PageHeader 和 Command Palette 迁入新契约。
3. 迁移 Literature、Tasks、Resources 和今日概览，验证三种页面原型。
4. 按 overlay/选择组件、表单组件、展示组件的顺序迁移到 shadcn 衍生实现；每个组件族单独验证，禁止全仓库一次性替换。
5. 通过静态检查逐步禁止新增 `--prism-*`、`--apple-*` 和未登记的硬编码颜色。
6. 最后删除无调用方的兼容 token；迁移脚本和设置升级保持版本化、可测试、与运行时组件解耦。

## 13. 验收

- 浅色和深色官方主题均通过代表页面截图、对比度和键盘验证。
- 主题切换只修改语义 token，不需要业务组件判断主题 ID。
- 第三方主题无效输入可安全拒绝并回退。
- Noto Sans 400/500/600/700 拉丁子集可离线加载；无字体资产时系统字体回退稳定，且不会产生未声明的伪字重。
- 新增组件不消费旧 `prism` / `apple` token。
- shadcn/Radix 来源组件由 `osci` 设计系统统一封装，业务代码没有形成新的直接耦合。
