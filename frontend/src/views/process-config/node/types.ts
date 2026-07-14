import type { ProcessLibraryStatus } from '@/views/process-config/types';

export type ProcessNodeType = 'pretreatment' | 'hydrometallurgy' | 'pyrometallurgy' | 'post_treatment';

export type NodeDecimalValue = string | number;

export interface ProcessLibraryOptionItem {
  id: number;
  code: string;
  name: string;
  type: string;
  unit: string;
  status: ProcessLibraryStatus;
  output_type?: string | null;
}

export interface ProcessNodeMaterialInputPayload {
  material_id: number | null;
  amount_per_ton: NodeDecimalValue;
  unit: string;
  sort_order: number;
  remark?: string | null;
}

export interface ProcessNodeConsumablePayload {
  consumable_id: number | null;
  amount_per_ton: NodeDecimalValue;
  unit: string;
  sort_order: number;
  remark?: string | null;
}

export interface ProcessNodePublicServicePayload {
  public_service_id: number | null;
  amount_per_ton: NodeDecimalValue;
  unit: string;
  sort_order: number;
  remark?: string | null;
}

export interface ProcessNodeEquipmentPayload {
  equipment_name: string;
  equipment_type?: string | null;
  quantity: NodeDecimalValue;
  investment_amount: NodeDecimalValue;
  currency: string;
  sort_order: number;
  remark?: string | null;
}

export interface ProcessNodeOutputPayload {
  product_id: number | null;
  output_per_ton: NodeDecimalValue;
  unit: string;
  is_main_product: boolean;
  sort_order: number;
  remark?: string | null;
}

export interface ProcessNodePayload {
  code: string;
  name: string;
  node_type: ProcessNodeType;
  staff: NodeDecimalValue;
  area: NodeDecimalValue;
  description?: string | null;
  status: ProcessLibraryStatus;
  version: string;
  sort_order: number;
  remark?: string | null;
  material_inputs: ProcessNodeMaterialInputPayload[];
  consumables: ProcessNodeConsumablePayload[];
  public_services: ProcessNodePublicServicePayload[];
  equipment: ProcessNodeEquipmentPayload[];
  outputs: ProcessNodeOutputPayload[];
}

export interface ProcessNodeChildBase {
  id: number;
  node_id: number;
  unit: string;
  sort_order: number;
  remark?: string | null;
  is_deleted?: boolean;
  deleted_at?: string | null;
  created_at: string;
  updated_at: string;
}

export interface ProcessNodeMaterialInput extends ProcessNodeChildBase {
  material_id: number;
  amount_per_ton: string;
}

export interface ProcessNodeConsumable extends ProcessNodeChildBase {
  consumable_id: number;
  amount_per_ton: string;
}

export interface ProcessNodePublicService extends ProcessNodeChildBase {
  public_service_id: number;
  amount_per_ton: string;
}

export interface ProcessNodeEquipment extends ProcessNodeChildBase {
  equipment_name: string;
  equipment_type?: string | null;
  quantity: string;
  investment_amount: string;
  currency: string;
}

export interface ProcessNodeOutput extends ProcessNodeChildBase {
  product_id: number;
  output_type?: string | null;
  output_per_ton: string;
  is_main_product: boolean;
}

export interface ProcessNodeItem {
  id: number;
  code: string;
  name: string;
  node_type: ProcessNodeType;
  staff: string;
  area: string;
  description?: string | null;
  status: ProcessLibraryStatus;
  version: string;
  sort_order: number;
  remark?: string | null;
  created_by?: number | null;
  updated_by?: number | null;
  is_deleted?: boolean;
  deleted_at?: string | null;
  created_at: string;
  updated_at: string;
}

export interface ProcessNodeDetail extends ProcessNodeItem {
  material_inputs: ProcessNodeMaterialInput[];
  consumables: ProcessNodeConsumable[];
  public_services: ProcessNodePublicService[];
  equipment: ProcessNodeEquipment[];
  outputs: ProcessNodeOutput[];
}

export interface ProcessNodeListParams {
  keyword?: string;
  node_type?: ProcessNodeType;
  status?: ProcessLibraryStatus;
  page?: number;
  page_size?: number;
}

export const PROCESS_NODE_TYPE_OPTIONS: readonly { label: string; value: ProcessNodeType }[] = [
  { label: '预处理', value: 'pretreatment' },
  { label: '湿法冶金', value: 'hydrometallurgy' },
  { label: '火法冶金', value: 'pyrometallurgy' },
  { label: '后处理', value: 'post_treatment' },
];
