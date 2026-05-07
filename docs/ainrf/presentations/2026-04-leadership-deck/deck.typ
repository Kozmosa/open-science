#import "@preview/touying:0.6.1": *
#import themes.simple: *

#show: simple-theme.with(
  aspect-ratio: "16-9",
  footer: [AINRF 领导汇报 · 2026-04],
)

// ==================== Slide 1: 封面 ====================
= AINRF：Agent-Driven 科研控制面

#v(1fr)

#align(center)[
  #text(1.3em)[减少科研重复劳动，而非替代研究者]

  #v(0.8em)

  #text(0.9em, gray)[
    已交付：CLI + FastAPI 后端 + React WebUI \
    environment · workspace · terminal · task · code-server
  ]
]

#v(1fr)

#align(center)[
  #text(0.8em, gray)[scholar-agent / AINRF · 2026-04]
]

// ==================== Slide 2: 为什么要做 ====================
= 为什么要做：科研辅助中的四类时间浪费

#v(0.5em)

#align(center)[
  #grid(
    columns: (1fr, 1fr),
    rows: (auto, auto),
    gutter: 1.5em,
    [
      #text(1.2em)[🔧] \
      #text(1.1em)[*配环境*] \
      #text(0.85em, gray)[新机器、新仓库、新依赖，反复踩坑]
    ],
    [
      #text(1.2em)[📁] \
      #text(1.1em)[*找入口*] \
      #text(0.85em, gray)[仓库结构复杂，找不到 baseline 运行命令]
    ],
    [
      #text(1.2em)[🔄] \
      #text(1.1em)[*复现 baseline*] \
      #text(0.85em, gray)[论文代码跑不通，调试成本极高]
    ],
    [
      #text(1.2em)[👁] \
      #text(1.1em)[*人工值守长任务*] \
      #text(0.85em, gray)[训练、网格搜索需要人盯着终端]
    ],
  )
]

#v(1fr)

#align(center)[
  #text(1.1em)[
    目标：把人从*低价值操作*中解放出来， \
    让研究者专注*提出问题*和*判断结果*
  ]
]

// ==================== Slide 3: 已交付什么 ====================
= 今天已经交付了什么

#v(0.5em)

#grid(
  columns: (1fr, 1fr),
  gutter: 1.2em,
  [
    == 三层产品面

    - #text(1.05em)[*`ainrf` CLI*] — 可安装、可服务化、可初始化
    - #text(1.05em)[*FastAPI 后端*] — environments / workspaces / \
      terminal / tasks / code 路由
    - #text(1.05em)[*React WebUI*] — Tasks / Workspaces / Settings / \
      Terminal / Code-Server
  ],
  [
    == 运行时能力

    - environment 管理 + profile 默认值
    - workspace 绑定 + seed 配置
    - personal terminal（keepalive）
    - Task Harness v1（SSE 流 + SQLite 回放）
    - workspace browser（code-server）
    - settings baseline（浏览器本地持久化）
  ],
)

#v(0.8em)

#align(center)[
  #box(fill: rgb("e8f5e9"), inset: 0.6em, radius: 4pt)[
    #text(1.05em)[
      关键主张：*可启动、可观察、可回看* — 不讲未来态大愿景
    ]
  ]
]

// ==================== Slide 4: 核心价值链路 ====================
= 远程服务 AI Agent 如何加速科研

#v(0.5em)

#align(center)[
  #text(1.05em)[
    用户在 WebUI 选择 *Workspace* + *Environment* → 输入任务描述
  ]
]

#v(0.5em)

#grid(
  columns: (1.2fr, 1fr),
  gutter: 1em,
  [
    == 五层 Prompt 组合
    #text(0.9em)[
      1. *Global harness* — 系统级指令 \
      2. *Workspace* — 工作区上下文 \
      3. *Environment* — 环境配置 \
      4. *Task profile* — 执行风格 \
      5. *Task input* — 用户描述
    ]
  ],
  [
    == 执行与回传
    #text(0.9em)[
      - 本地或 *SSH 远程*启动 Claude Code
      - 输出经 *SSE 流*实时回传前端
      - 全部写入 *SQLite*持久化
      - 浏览器关闭后可*回放*完整输出
    ]
  ],
)

#v(0.6em)

#align(center)[
  #box(fill: rgb("fff3e0"), inset: 0.6em, radius: 4pt)[
    #text(1.05em)[
      核心转变：从 *"人盯终端"* → *"可监控、可回放"*
    ]
  ]
]

// ==================== Slide 5: 为什么更省时间 ====================
= 为什么比直接手工跑 Agent 更省时间

#v(0.5em)

#grid(
  columns: (1fr, 1fr),
  rows: (auto, auto),
  gutter: 1.2em,
  [
    #box(fill: rgb("e3f2fd"), inset: 0.6em, radius: 4pt)[
      #text(1.05em)[*1. 一键联调*] \
      #text(0.85em)[`scripts/webui.sh` 同时拉起前后端，降低启动摩擦]
    ]
  ],
  [
    #box(fill: rgb("f3e5f5"), inset: 0.6em, radius: 4pt)[
      #text(1.05em)[*2. 减少重复输入*] \
      #text(0.85em)[seed workspace + environment profile + settings 默认值]
    ]
  ],
  [
    #box(fill: rgb("e8f5e9"), inset: 0.6em, radius: 4pt)[
      #text(1.05em)[*3. 可监控、可回放*] \
      #text(0.85em)[Task Harness SSE 流 + SQLite 持久化，不用人盯]
    ]
  ],
  [
    #box(fill: rgb("fff3e0"), inset: 0.6em, radius: 4pt)[
      #text(1.05em)[*4. 远程文件浏览*] \
      #text(0.85em)[workspace browser 在浏览器内直接翻远程目录]
    ]
  ],
)

// ==================== Slide 6: Skills + ARIS ====================
= 正在推进的下一层能力：Skills + ARIS 基座

#v(0.5em)

#grid(
  columns: (1fr, 1fr),
  gutter: 1.2em,
  [
    == Skills 能力层

    #text(0.9em)[
      目标：把常见 research-dev workflow 模块化成 skill

      - `project-init` — 项目初始化脚手架
      - `env-bootstrap` — 环境自动配置
      - `git-workflow` — 分支/worktree 规范
      - `commit-style` — 提交信息规范
      - `repo-ops` — 仓库日常操作
    ]

    #v(0.5em)

    #box(fill: rgb("ffebee"), inset: 0.5em, radius: 4pt)[
      #text(0.85em)[
        *标注*：当前 skills 层主要处于*设计推进中*， \
        底层控制面已具备承载条件
      ]
    ]
  ],
  [
    == ARIS 基座接入

    #text(0.9em)[
      - test/ 目录已完成 ARIS 探索实验
      - 覆盖 idea discovery、实验验证、结果分析
      - 示例：partition-first federated traffic forecasting
      - 后续将 ARIS 接入作为 *VSA*（Virtual Research Assistant）基座之一
    ]

    #v(0.5em)

    #box(fill: rgb("e8f5e9"), inset: 0.5em, radius: 4pt)[
      #text(0.85em)[
        ARIS 提供研究能力，AINRF 提供控制面， \
        两者互补形成完整科研辅助栈
      ]
    ]
  ],
)

// ==================== Slide 7: 收尾 ====================
= 下一步：争取继续支持

#v(1fr)

#align(center)[
  #text(1.1em)[
    三个具体落点
  ]

  #v(1em)

  #grid(
    columns: (1fr, 1fr, 1fr),
    gutter: 1em,
    [
      #box(fill: rgb("e3f2fd"), inset: 0.6em, radius: 4pt)[
        #text(1em)[*1. Skills 层落地*] \
        #text(0.85em)[接到现有控制面上运行]
      ]
    ],
    [
      #box(fill: rgb("f3e5f5"), inset: 0.6em, radius: 4pt)[
        #text(1em)[*2. 度量指标*] \
        #text(0.85em)[任务成功率、环境配置时间等]
      ]
    ],
    [
      #box(fill: rgb("e8f5e9"), inset: 0.6em, radius: 4pt)[
        #text(1em)[*3. 真实场景试点*] \
        #text(0.85em)[交通联邦预测等科研场景]
      ]
    ],
  )

  #v(1.5em)

  #box(fill: rgb("fff3e0"), inset: 0.8em, radius: 4pt)[
    #text(1.15em)[
      目标不是 *"24×7 自治科研引擎"* \
      而是 *"真正有用的科研辅助工具"*
    ]
  ]
]

#v(1fr)

#align(center)[
  #text(0.9em, gray)[
    scholar-agent / AINRF · 感谢各位领导支持
  ]
]
