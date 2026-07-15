import { request } from '@/api/request';
import type {
  ProcessConfigImportResult,
  ProcessConfigModuleKey,
  ProcessLibraryItem,
  ProcessLibraryListParams,
  ProcessLibraryPayload,
  ProcessLibraryStatus,
} from '@/views/process-config/types';
import type {
  ProcessLibraryOptionItem,
  ProcessNodeDetail,
  ProcessNodeItem,
  ProcessNodeListParams,
  ProcessNodePayload,
} from '@/views/process-config/node/types';
import type {
  ProcessRouteDetail,
  ProcessRouteItem,
  ProcessRouteListParams,
  ProcessRouteNode,
  ProcessRouteNodeAddPayload,
  ProcessRouteNodeReorderPayload,
  ProcessRoutePayload,
  ProcessRouteTreePreview,
  ProcessRouteVersion,
  ProcessRouteVersionCreatePayload,
} from '@/views/process-config/route/types';
import type { PageResult } from '@/types/api';
import type {
  ProcessCalculatorOptions,
  ProcessCalculatorRequest,
  ProcessCalculatorResult,
} from '@/views/process-config/calculator/types';

export function getProcessCalculatorOptions(): Promise<ProcessCalculatorOptions> {
  return request.get('/process-config/calculator/options') as Promise<ProcessCalculatorOptions>;
}

export function calculateProcessFinancialModel(payload: ProcessCalculatorRequest): Promise<ProcessCalculatorResult> {
  return request.post('/process-config/calculator/calculate', payload) as Promise<ProcessCalculatorResult>;
}

export function downloadProcessConfigTemplate(moduleKey: ProcessConfigModuleKey): Promise<Blob> {
  return request.get(`/process-config/${moduleKey}/template`, {
    responseType: 'blob',
    timeout: 120000,
  }) as Promise<Blob>;
}

export function exportProcessConfigData(moduleKey: ProcessConfigModuleKey, params?: Record<string, unknown>): Promise<Blob> {
  return request.get(`/process-config/${moduleKey}/export`, {
    params,
    responseType: 'blob',
    timeout: 120000,
  }) as Promise<Blob>;
}

export function importProcessConfigData(moduleKey: ProcessConfigModuleKey, file: File): Promise<ProcessConfigImportResult> {
  const formData = new FormData();
  formData.append('file', file);
  return request.post(`/process-config/${moduleKey}/import`, formData, { timeout: 120000 }) as Promise<ProcessConfigImportResult>;
}

export function listProcessLibrary(
  basePath: string,
  params?: ProcessLibraryListParams,
): Promise<PageResult<ProcessLibraryItem>> {
  return request.get(basePath, { params }) as Promise<PageResult<ProcessLibraryItem>>;
}

export function createProcessLibrary(basePath: string, payload: ProcessLibraryPayload): Promise<ProcessLibraryItem> {
  return request.post(basePath, payload) as Promise<ProcessLibraryItem>;
}

export function getProcessLibrary(basePath: string, id: number): Promise<ProcessLibraryItem> {
  return request.get(`${basePath}/${id}`) as Promise<ProcessLibraryItem>;
}

export function updateProcessLibrary(basePath: string, id: number, payload: ProcessLibraryPayload): Promise<ProcessLibraryItem> {
  return request.put(`${basePath}/${id}`, payload) as Promise<ProcessLibraryItem>;
}

export function deleteProcessLibrary(basePath: string, id: number): Promise<{ deleted: boolean }> {
  return request.delete(`${basePath}/${id}`) as Promise<{ deleted: boolean }>;
}

export function updateProcessLibraryStatus(
  basePath: string,
  id: number,
  status: Extract<ProcessLibraryStatus, 'enabled' | 'disabled'>,
): Promise<ProcessLibraryItem> {
  return request.patch(`${basePath}/${id}/status`, { status }) as Promise<ProcessLibraryItem>;
}

export function listProcessLibraryOptions(
  optionPath: string,
  params?: Record<string, unknown>,
): Promise<ProcessLibraryOptionItem[]> {
  return request.get(`/process-config/options/${optionPath}`, { params }) as Promise<ProcessLibraryOptionItem[]>;
}

export function listProcessNodes(params?: ProcessNodeListParams): Promise<PageResult<ProcessNodeItem>> {
  return request.get('/process-config/nodes', { params }) as Promise<PageResult<ProcessNodeItem>>;
}

export function createProcessNode(payload: ProcessNodePayload): Promise<ProcessNodeDetail> {
  return request.post('/process-config/nodes', payload) as Promise<ProcessNodeDetail>;
}

export function getProcessNode(id: number): Promise<ProcessNodeDetail> {
  return request.get(`/process-config/nodes/${id}`) as Promise<ProcessNodeDetail>;
}

export function updateProcessNode(id: number, payload: ProcessNodePayload): Promise<ProcessNodeDetail> {
  return request.put(`/process-config/nodes/${id}`, payload) as Promise<ProcessNodeDetail>;
}

export function deleteProcessNode(id: number): Promise<{ deleted: boolean }> {
  return request.delete(`/process-config/nodes/${id}`) as Promise<{ deleted: boolean }>;
}

export function listProcessRoutes(params?: ProcessRouteListParams): Promise<PageResult<ProcessRouteItem>> {
  return request.get('/process-config/routes', { params }) as Promise<PageResult<ProcessRouteItem>>;
}

export function createProcessRoute(payload: ProcessRoutePayload): Promise<ProcessRouteDetail> {
  return request.post('/process-config/routes', payload) as Promise<ProcessRouteDetail>;
}

export function getProcessRoute(id: number): Promise<ProcessRouteDetail> {
  return request.get(`/process-config/routes/${id}`) as Promise<ProcessRouteDetail>;
}

export function getProcessRouteTreePreview(id: number): Promise<ProcessRouteTreePreview> {
  return request.get(`/process-config/routes/${id}/tree-preview`) as Promise<ProcessRouteTreePreview>;
}

export function updateProcessRoute(id: number, payload: ProcessRoutePayload): Promise<ProcessRouteDetail> {
  return request.put(`/process-config/routes/${id}`, payload) as Promise<ProcessRouteDetail>;
}

export function deleteProcessRoute(id: number): Promise<{ deleted: boolean }> {
  return request.delete(`/process-config/routes/${id}`) as Promise<{ deleted: boolean }>;
}

export function addProcessRouteNode(routeId: number, payload: ProcessRouteNodeAddPayload): Promise<ProcessRouteNode> {
  return request.post(`/process-config/routes/${routeId}/nodes`, payload) as Promise<ProcessRouteNode>;
}

export function reorderProcessRouteNodes(routeId: number, payload: ProcessRouteNodeReorderPayload): Promise<ProcessRouteNode[]> {
  return request.put(`/process-config/routes/${routeId}/nodes/reorder`, payload) as Promise<ProcessRouteNode[]>;
}

export function deleteProcessRouteNode(routeId: number, routeNodeId: number): Promise<{ deleted: boolean }> {
  return request.delete(`/process-config/routes/${routeId}/nodes/${routeNodeId}`) as Promise<{ deleted: boolean }>;
}

export function copyProcessRoute(id: number): Promise<ProcessRouteDetail> {
  return request.post(`/process-config/routes/${id}/copy`) as Promise<ProcessRouteDetail>;
}

export function listProcessRouteVersions(routeId: number): Promise<ProcessRouteVersion[]> {
  return request.get(`/process-config/routes/${routeId}/versions`) as Promise<ProcessRouteVersion[]>;
}

export function createProcessRouteVersion(routeId: number, payload: ProcessRouteVersionCreatePayload): Promise<ProcessRouteVersion> {
  return request.post(`/process-config/routes/${routeId}/versions`, payload) as Promise<ProcessRouteVersion>;
}
