import {
  Activity,
  BookOpen,
  Boxes,
  Clock,
  FolderKanban,
  FolderOpen,
  History,
  House,
  LayoutGrid,
  ListChecks,
  Settings,
  SquareTerminal,
  type LucideIcon,
} from 'lucide-react';
import type { MessageKey } from '@/shared/i18n';

export type AppRouteId =
  | 'today'
  | 'projects'
  | 'terminal'
  | 'tasks'
  | 'workspaces'
  | 'workspace-browser'
  | 'environments'
  | 'resources'
  | 'sessions'
  | 'timeline'
  | 'literature'
  | 'settings';

export interface AppRouteDefinition {
  id: AppRouteId;
  path: string;
  titleKey: MessageKey;
  descriptionKey: MessageKey;
  icon: LucideIcon;
  navigation: boolean;
  adminOnly?: boolean;
  keywords: readonly string[];
}

export interface ResolvedAppRoute extends AppRouteDefinition {
  label: string;
  description: string;
}

export const ROUTE_REGISTRY: readonly AppRouteDefinition[] = [
  { id: 'today', path: '/today', titleKey: 'navigation.today.label', descriptionKey: 'navigation.today.description', icon: House, navigation: true, keywords: ['today', 'overview', 'attention', 'progress', 'continue'] },
  { id: 'projects', path: '/projects', titleKey: 'navigation.projects.label', descriptionKey: 'navigation.projects.description', icon: LayoutGrid, navigation: true, keywords: ['projects', 'research', 'canvas'] },
  { id: 'terminal', path: '/terminal', titleKey: 'navigation.terminal.label', descriptionKey: 'navigation.terminal.description', icon: SquareTerminal, navigation: true, keywords: ['terminal', 'shell', 'console'] },
  { id: 'tasks', path: '/tasks', titleKey: 'navigation.tasks.label', descriptionKey: 'navigation.tasks.description', icon: ListChecks, navigation: true, keywords: ['tasks', 'attempts', 'agents', 'runs'] },
  { id: 'workspaces', path: '/workspaces', titleKey: 'navigation.workspaces.label', descriptionKey: 'navigation.workspaces.description', icon: FolderKanban, navigation: true, keywords: ['workspaces', 'repositories', 'paths'] },
  { id: 'workspace-browser', path: '/workspace-browser', titleKey: 'navigation.workspaceBrowser.label', descriptionKey: 'navigation.workspaceBrowser.description', icon: FolderOpen, navigation: false, keywords: ['browse files', 'workspace browser', 'files'] },
  { id: 'environments', path: '/environments', titleKey: 'navigation.environments.label', descriptionKey: 'navigation.environments.description', icon: Boxes, navigation: true, keywords: ['containers', 'environments', 'runtime'] },
  { id: 'resources', path: '/resources', titleKey: 'navigation.resources.label', descriptionKey: 'navigation.resources.description', icon: Activity, navigation: true, keywords: ['resources', 'cpu', 'gpu', 'memory'] },
  { id: 'sessions', path: '/sessions', titleKey: 'navigation.sessions.label', descriptionKey: 'navigation.sessions.description', icon: History, navigation: true, adminOnly: true, keywords: ['task runs', 'sessions', 'history'] },
  { id: 'timeline', path: '/timeline', titleKey: 'navigation.timeline.label', descriptionKey: 'navigation.timeline.description', icon: Clock, navigation: true, adminOnly: true, keywords: ['timeline', 'gantt', 'schedule'] },
  { id: 'literature', path: '/literature', titleKey: 'nav.literature', descriptionKey: 'nav.literature', icon: BookOpen, navigation: true, keywords: ['literature', 'papers', 'arxiv', 'reading'] },
  { id: 'settings', path: '/settings', titleKey: 'navigation.settings.label', descriptionKey: 'navigation.settings.description', icon: Settings, navigation: true, keywords: ['settings', 'preferences', 'configuration'] },
] as const;

export function getRouteDefinition(pathname: string): AppRouteDefinition | undefined {
  return ROUTE_REGISTRY.find((route) => route.path === pathname);
}

export function getVisibleRoutes(isAdmin: boolean, navigationOnly = false): AppRouteDefinition[] {
  return ROUTE_REGISTRY.filter((route) => (!navigationOnly || route.navigation) && (!route.adminOnly || isAdmin));
}

export function getRoutePath(id: string): string | undefined {
  return ROUTE_REGISTRY.find((route) => route.id === id)?.path;
}
