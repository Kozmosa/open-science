# 小红书文案：ARIS 介绍

---

**标题：** 睡一觉起来论文从5分变7.5分？开源AI科研神器ARIS⚔️

---

睡前丢给AI一篇论文，醒来发现：
❌ 站不住的claim被砍了
✅ 20+个GPU实验跑完了
📝 叙事框架重写了
🎯 分数从5.0拉到7.5

这不是科幻，这是我们开源的 ARIS ⚔️

—

🔥 ARIS 是什么？

全称 Auto-Research-In-Sleep
一套 Claude Code 自定义 Skills
核心机制：两个AI互相搞对方

Claude Code = 执行者（写代码、跑实验、改论文）
GPT-5.5 xhigh = 审稿人（打分、挑毛病、提修改）

关键：它们互不评自己的作业
这才是真正的反馈循环 🔁

—

⚔️ 为什么叫 ARIS？

ARIS = 希腊战神阿瑞斯
寓意：用AI武装你的科研战斗力
（也是 Auto Research In Sleep 的缩写啦）

—

💡 两大工作流

📍 工作流1：找 Idea
给一个研究方向，自动完成：
📚 调研全景 → 🧠 头脑风暴12个idea → 🔍 查新过滤 → 🛡️ 深度验证 → 🧪 并行pilot实验 → 🏆 排序出报告

输出一份 IDEA_REPORT.md
哪个idea有信号、哪个该放弃，一目了然

📍 工作流2：自动改论文
丢进去一篇论文，自动循环：
审稿 → 修bug → 跑实验 → 再审 → 再改...
最多4轮，达标自动停

真实数据👇
第1轮 6.5/10 补了标准指标
第2轮 6.8/10 核心claim翻车，转叙事
第3轮 7.0/10 大规模seed研究推翻主claim
第4轮 7.5/10 ✅ 诊断证据确立，可投稿

—

🛡️ 不是无脑流水线

⚠️ 内置安全机制：
• 最多4轮，防无限循环
• >4 GPU小时的实验自动跳过
• 优先改叙事，不乱烧卡
• 明确规则：不许隐藏弱点骗高分
• 必须真改了才能重新review

而且我们在README里写了：
「最好的研究 = 人的洞察 + AI的执行力，不是全自动流水线」

AI帮你加速，但最终决策权在你 🧠

—

🧰 11个Skills一览

💡 idea-creator — 自动找idea
🔬 research-review — GPT-5.5深度审稿
🔁 auto-review-loop — 自动循环改到过
📚 research-lit — 搜论文找gap
📊 analyze-results — 分析实验结果
👀 monitor-experiment — 监控实验进度
🔍 novelty-check — 查新防撞车
🚀 run-experiment — 一键部署GPU实验
🎨 pixel-art — 像素风插图生成
🔭 idea-discovery — 工作流1全流程（调研→生成→查新→review）
🏗️ research-pipeline — 完整流水线（找idea→实现→自动改到投稿）

—

⚙️ 三步安装

1️⃣ 装 Claude Code
2️⃣ 装 Codex MCP（review类需要）
3️⃣ cp -r skills/* ~/.claude/skills/

就这么简单 🎯

—

📊 适合谁？

✅ ML/NLP方向的研究生和博后
✅ 有GPU但时间不够的独立研究者
✅ 想系统化科研流程的实验室
✅ 在写survey想找idea的同学

❌ 不适合：指望AI完全替代思考的人
（AI是武器，不是将军）

—

🔗 GitHub：
github.com/wanshuiyin/Auto-claude-code-research-in-sleep

MIT开源，fork随便改 ⭐
Skills就是Markdown文件，零门槛定制

—

#ClaudeCode #AI科研 #论文写作 #研究生必备 #开源工具 #GPT #机器学习 #深度学习 #科研工具 #ARIS
