import { defineConfig } from 'astro/config';
import starlight from '@astrojs/starlight';
import promqlLanguage from './src/languages/promql.mjs';

// https://astro.build/config
export default defineConfig({
  site: 'https://kozmosa.github.io',
  base: '/open-science/',
  outDir: './dist',
  integrations: [
    starlight({
      title: 'OpenScience',
      disable404Route: true,
      expressiveCode: {
        shiki: {
          langs: [promqlLanguage],
        },
      },
      sidebar: [
        {
          label: '快速开始',
          slug: 'quickstart',
          badge: { text: '新', variant: 'tip' },
        },
        {
          label: '使用指南',
          collapsed: false,
          items: [
            { label: 'CLI 参考', slug: 'cli' },
            { label: 'WebUI 总览', slug: 'webui' },
            { label: '认证与授权', slug: 'auth' },
            { label: '项目管理', slug: 'projects' },
            { label: '终端管理', slug: 'terminal' },
            { label: '工作区', slug: 'workspace' },
            { label: '会话追踪', slug: 'sessions' },
            { label: '时间线', slug: 'timeline' },
            { label: '资源监控', slug: 'resources' },
            { label: '系统设置', slug: 'settings' },
          ],
        },
        {
          label: '部署',
          collapsed: false,
          items: [
            { label: '部署概览', slug: 'deployment' },
            { label: '裸机部署', slug: 'deployment/bare-metal' },
            { label: 'Docker Compose', slug: 'deployment/docker' },
            { label: 'Kubernetes', slug: 'deployment/kubernetes' },
          ],
        },
        {
          label: '安全',
          collapsed: false,
          items: [
            { label: '安全架构', slug: 'security' },
            { label: '生产检查清单', slug: 'security/checklist' },
          ],
        },
        {
          label: '可观测性',
          collapsed: false,
          items: [
            { label: '可观测性概览', slug: 'observability' },
            { label: '审计日志', slug: 'observability/audit-logs' },
            { label: 'Prometheus 指标', slug: 'observability/metrics' },
            { label: '监控栈', slug: 'observability/monitoring-stack' },
          ],
        },
        {
          label: '开发',
          collapsed: true,
          items: [
            { label: '开发指南', slug: 'development' },
          ],
        },
      ],
      customCss: ['./src/custom.css'],
      editLink: {
        baseUrl:
          'https://github.com/Kozmosa/open-science/edit/master/docs-site/',
      },
      lastUpdated: true,
      head: [
        {
          tag: 'meta',
          attrs: { name: 'docsearch:language', content: 'zh-CN' },
        },
      ],
    }),
  ],
});
