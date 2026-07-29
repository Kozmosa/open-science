import { transportOperations } from '@/generated/transport';
import type { http as mswHttp } from 'msw';

export type TransportOperationId = keyof typeof transportOperations;

export function transportPath<OperationId extends TransportOperationId>(
  operationId: OperationId,
  pathParameters: Record<string, string> = {},
): string {
  let path: string = transportOperations[operationId].clientPath;
  for (const [name, value] of Object.entries(pathParameters)) {
    path = path.replace(`{${name}}`, encodeURIComponent(value));
  }
  if (path.includes('{')) {
    throw new Error(`Missing path parameter for ${operationId}: ${path}`);
  }
  return path;
}

type TransportMethod = (typeof transportOperations)[TransportOperationId]['method'];

const canonicalOperations = Object.entries(transportOperations) as Array<
  [TransportOperationId, (typeof transportOperations)[TransportOperationId]]
>;

function normalizeConcretePath(path: string): string {
  return path.split('?', 1)[0] ?? path;
}

function templateMatches(template: string, concretePath: string): boolean {
  const templateSegments = template.split('/');
  const pathSegments = concretePath.split('/');
  return (
    templateSegments.length === pathSegments.length &&
    templateSegments.every(
      (segment, index) =>
        (segment.startsWith('{') && segment.endsWith('}')) || segment === pathSegments[index],
    )
  );
}

export function assertTransportRequest(method: TransportMethod, clientPath: string): void {
  const concretePath = normalizeConcretePath(clientPath);
  const match = canonicalOperations.some(
    ([, operation]) =>
      operation.canonical &&
      operation.method === method &&
      templateMatches(operation.clientPath, concretePath),
  );
  if (!match) {
    throw new Error(`Unknown generated transport operation: ${method} ${concretePath}`);
  }
}

function normalizeMswPath(path: string): string {
  return path
    .replace(/^\/api/, '')
    .replace(/:([A-Za-z_][A-Za-z0-9_]*)/g, '{$1}');
}

export function createTransportMockAdapter(http: typeof mswHttp): typeof mswHttp {
  return new Proxy(http, {
    get(target, property, receiver) {
      const original = Reflect.get(target, property, receiver);
      const method = String(property).toUpperCase();
      if (
        typeof original !== 'function' ||
        !['DELETE', 'GET', 'HEAD', 'OPTIONS', 'PATCH', 'POST', 'PUT'].includes(method)
      ) {
        return original;
      }
      return (path: string | RegExp, ...handlers: unknown[]) => {
        if (typeof path === 'string') {
          assertTransportRequest(method as TransportMethod, normalizeMswPath(path));
        }
        return Reflect.apply(original, target, [path, ...handlers]);
      };
    },
  }) as typeof mswHttp;
}
