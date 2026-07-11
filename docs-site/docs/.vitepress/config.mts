import { defineConfig } from "vitepress";
import promqlLanguage from "./languages/promql.mjs";

export default defineConfig({
  title: "OpenScience",
  description: "OpenScience 产品文档",
  base: "/open-science/",
  outDir: "../dist",
  cleanUrls: true,
  lastUpdated: true,
  markdown: {
    languages: [promqlLanguage],
  },
  themeConfig: {
    nav: [
      { text: "快速开始", link: "/quickstart" },
      { text: "部署", link: "/deployment/" },
      { text: "开发", link: "/development" },
    ],
    sidebar: [
      { text: "快速开始", items: [{ text: "快速开始", link: "/quickstart" }] },
      {
        text: "使用指南",
        items: [
          { text: "CLI 参考", link: "/cli" }, { text: "WebUI 总览", link: "/webui" },
          { text: "认证与授权", link: "/auth" }, { text: "项目管理", link: "/projects" },
          { text: "终端管理", link: "/terminal" }, { text: "工作区", link: "/workspace" },
          { text: "会话追踪", link: "/sessions" }, { text: "时间线", link: "/timeline" },
          { text: "资源监控", link: "/resources" }, { text: "系统设置", link: "/settings" },
        ],
      },
      { text: "部署", items: [{ text: "部署概览", link: "/deployment/" }, { text: "裸机部署", link: "/deployment/bare-metal" }, { text: "Docker Compose", link: "/deployment/docker" }, { text: "Kubernetes", link: "/deployment/kubernetes" }] },
      { text: "安全", items: [{ text: "安全架构", link: "/security/" }, { text: "生产检查清单", link: "/security/checklist" }] },
      { text: "可观测性", items: [{ text: "可观测性概览", link: "/observability/" }, { text: "审计日志", link: "/observability/audit-logs" }, { text: "Prometheus 指标", link: "/observability/metrics" }, { text: "监控栈", link: "/observability/monitoring-stack" }] },
      { text: "开发", collapsed: true, items: [{ text: "开发指南", link: "/development" }] },
    ],
    socialLinks: [{ icon: "github", link: "https://github.com/Kozmosa/open-science" }],
    editLink: { pattern: "https://github.com/Kozmosa/open-science/edit/master/docs-site/docs/:path", text: "在 GitHub 上编辑此页" },
    search: { provider: "local" },
  },
});
