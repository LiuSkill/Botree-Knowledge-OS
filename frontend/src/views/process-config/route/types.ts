import type { PermissionCode } from '@/constants/permissions';
import type { ProcessLibraryItem, ProcessLibraryStatus } from '@/views/process-config/types';
import type { ProcessNodeDetail, ProcessNodeItem } from '@/views/process-config/node/types';

export interface ProcessRouteNodePayload {
  node_id: number | null;
  sort_order: number;
  node_params_json?: string | null;
  remark?: string | null;
}

export interface ProcessRoutePayload {
  code: string;
  name: string;
  input_material_id: number | null;
  final_product_id: number | null;
  version: string;
  description?: string | null;
  status: ProcessLibraryStatus;
  sort_order: number;
  remark?: string | null;
  nodes: ProcessRouteNodePayload[];
}

export interface ProcessCalculationOutputPayload {
  output_type: 'product' | 'byproduct' | 'solid_waste' | 'wastewater';
  product_id: number | null;
  output_name: string;
  spec?: string | null;
  formula_type: 'fixed' | 'expression';
  recovery_rate: string | number;
  balance_weight: string | number;
  unit: string;
  output_ratio: string | number;
  expression?: string | null;
  treatment_cost: string | number;
  sort_order: number;
  remark?: string | null;
}

export interface ProcessCalculationOutput extends ProcessCalculationOutputPayload {
  id: number;
  route_id: number;
}

export interface ProcessRouteItem {
  id: number;
  code: string;
  name: string;
  input_material_id: number;
  final_product_id: number;
  version: string;
  description?: string | null;
  status: ProcessLibraryStatus;
  sort_order: number;
  remark?: string | null;
  input_material_name?: string | null;
  final_product_name?: string | null;
  node_count: number;
  created_by?: number | null;
  updated_by?: number | null;
  created_at: string;
  updated_at: string;
}

export interface ProcessRouteNode {
  id: number;
  route_id: number;
  node_id: number;
  sort_order: number;
  node_params_json?: string | null;
  remark?: string | null;
  is_deleted?: boolean;
  deleted_at?: string | null;
  created_at: string;
  updated_at: string;
}

export interface ProcessRouteNodeDetail extends ProcessRouteNode {
  node: ProcessNodeDetail;
}

export interface ProcessRouteDetail {
  route: ProcessRouteItem;
  input_material: ProcessLibraryItem;
  final_product: ProcessLibraryItem;
  nodes: ProcessRouteNodeDetail[];
}

export interface ProcessRouteVersion {
  id: number;
  route_id: number;
  version_no: number;
  snapshot_json: string;
  change_log?: string | null;
  created_by?: number | null;
  is_deleted?: boolean;
  deleted_at?: string | null;
  created_at: string;
  updated_at: string;
}

export interface ProcessRouteListParams {
  keyword?: string;
  input_material_id?: number;
  final_product_id?: number;
  status?: ProcessLibraryStatus;
  page?: number;
  page_size?: number;
}

export interface ProcessRouteNodeAddPayload extends ProcessRouteNodePayload {
  node_id: number;
}

export interface ProcessRouteNodeReorderItem {
  route_node_id: number;
  sort_order: number;
}

export interface ProcessRouteNodeReorderPayload {
  items: ProcessRouteNodeReorderItem[];
}

export interface ProcessRouteVersionCreatePayload {
  version_no?: number | null;
  change_log?: string | null;
}

export interface ProcessRoutePermissions {
  view: PermissionCode;
  create: PermissionCode;
  update: PermissionCode;
  delete: PermissionCode;
  import: PermissionCode;
  export: PermissionCode;
  version: PermissionCode;
}

export interface RouteEditableNode {
  local_key: string;
  route_node_id?: number;
  node_id: number | null;
  sort_order: number;
  node_params_json?: string | null;
  remark?: string | null;
}

export interface RouteFlowNode {
  local_key: string;
  route_node_id?: number;
  node_id: number;
  sort_order: number;
  node_name: string;
  node_code: string;
  node_type: string;
  version: string;
  status: ProcessLibraryStatus;
  remark?: string | null;
  node_params_json?: string | null;
}

export interface RouteNodeOption extends ProcessNodeItem {}

export type RouteTreePreviewNodeKind = 'material' | 'node' | 'product' | 'waste';

export interface RouteTreePreviewNode {
  key: string;
  label: string;
  code?: string | null;
  meta?: string | null;
  kind: RouteTreePreviewNodeKind;
  active: boolean;
  children: RouteTreePreviewNode[];
}

export interface ProcessRouteTreeLibraryItem {
  id: number;
  code: string;
  name: string;
  unit?: string | null;
  output_type?: string | null;
}

export interface ProcessRouteTreeNodeOutput {
  id: number;
  product_id: number;
  output_type: 'product' | 'byproduct' | 'solid_waste' | 'wastewater';
  product?: ProcessRouteTreeLibraryItem | null;
}

export interface ProcessRouteTreeNode {
  route_node_id: number;
  node_id: number;
  code: string;
  name: string;
  node_type: string;
  version: string;
  sort_order: number;
  outputs: ProcessRouteTreeNodeOutput[];
}

export interface ProcessRouteTreeRoute {
  id: number;
  code: string;
  name: string;
  version: string;
  sort_order: number;
  input_material: ProcessRouteTreeLibraryItem;
  final_product: ProcessRouteTreeLibraryItem;
  nodes: ProcessRouteTreeNode[];
}

export interface ProcessRouteTreePreview {
  current_route_id: number;
  routes: ProcessRouteTreeRoute[];
}

export const PROCESS_ROUTE_STATUS_OPTIONS: readonly { label: string; value: ProcessLibraryStatus }[] = [
  { label: '启用', value: 'enabled' },
  { label: '草稿', value: 'draft' },
  { label: '停用', value: 'disabled' },
];

export function createEmptyRoutePayload(): ProcessRoutePayload {
  return {
    code: '',
    name: '',
    input_material_id: null,
    final_product_id: null,
    version: 'V1',
    description: '',
    status: 'enabled',
    sort_order: 0,
    remark: '',
    nodes: [],
  };
}
