import type { PermissionCode } from '@/constants/permissions';

export type ProcessLibraryStatus = 'enabled' | 'draft' | 'disabled';
export type ProcessRegionCode = 'asia' | 'europe' | 'americas';
export type ProcessRegionCurrency = 'CNY' | 'EUR' | 'USD';
export type ProcessConfigModuleKey = 'materials' | 'products' | 'consumables' | 'public-services' | 'nodes' | 'routes';

export interface ProcessLibraryTypeOption {
  label: string;
  value: string;
}

export interface ProcessRegionDefinition {
  region_code: ProcessRegionCode;
  region_name: string;
  currency: ProcessRegionCurrency;
}

export interface ProcessConfigModuleMeta {
  key: ProcessConfigModuleKey;
  label: string;
  filenamePrefix: string;
}

export const PROCESS_REGION_DEFINITIONS: readonly ProcessRegionDefinition[] = [
  { region_code: 'asia', region_name: '亚洲', currency: 'CNY' },
  { region_code: 'europe', region_name: '欧洲', currency: 'EUR' },
  { region_code: 'americas', region_name: '美洲', currency: 'USD' },
];

export const PROCESS_CONFIG_MODULE_META_MAP: Record<ProcessConfigModuleKey, ProcessConfigModuleMeta> = {
  materials: { key: 'materials', label: '原料库', filenamePrefix: 'process-materials' },
  products: { key: 'products', label: '产品库', filenamePrefix: 'process-products' },
  consumables: { key: 'consumables', label: '消耗品库', filenamePrefix: 'process-consumables' },
  'public-services': { key: 'public-services', label: '公共服务库', filenamePrefix: 'process-public-services' },
  nodes: { key: 'nodes', label: '工艺节点库', filenamePrefix: 'process-nodes' },
  routes: { key: 'routes', label: '工艺路线库', filenamePrefix: 'process-routes' },
};

export interface ProcessConfigImportError {
  sheet: string;
  row: number;
  field: string;
  message: string;
}

export interface ProcessConfigImportResult {
  module: ProcessConfigModuleKey;
  imported_count: number;
  imported_codes?: string[];
}

export interface ProcessRegionPrice {
  id?: number;
  owner_type?: string;
  owner_id?: number;
  region_code: ProcessRegionCode;
  region_name: string;
  currency: ProcessRegionCurrency;
  unit_price: string | number;
  unit: string;
  status: ProcessLibraryStatus;
  created_at?: string;
  updated_at?: string;
}

export interface ProcessLibraryItem {
  id: number;
  code: string;
  name: string;
  type: string;
  description?: string | null;
  unit: string;
  status: ProcessLibraryStatus;
  sort_order: number;
  remark?: string | null;
  region_prices: ProcessRegionPrice[];
  created_by?: number | null;
  updated_by?: number | null;
  created_at: string;
  updated_at: string;
}

export interface ProcessMaterialCompositionPayload {
  element_code: string;
  element_name: string;
  content_ratio: string | number;
  unit: string;
  remark?: string | null;
}

export interface ProcessMaterialComposition extends ProcessMaterialCompositionPayload {
  id: number;
  material_id: number;
}

export interface ProcessLibraryPayload {
  code: string;
  name: string;
  type: string;
  description?: string | null;
  unit: string;
  status: ProcessLibraryStatus;
  sort_order: number;
  remark?: string | null;
  region_prices: ProcessRegionPrice[];
}

export interface ProcessLibraryListParams {
  keyword?: string;
  type?: string;
  status?: ProcessLibraryStatus;
  page?: number;
  page_size?: number;
}

export interface ProcessLibraryPermissions {
  view: PermissionCode;
  create: PermissionCode;
  update: PermissionCode;
  delete: PermissionCode;
  import: PermissionCode;
  export: PermissionCode;
}

export interface ProcessLibraryPageConfig {
  title: string;
  entityName: string;
  moduleKey: ProcessConfigModuleKey;
  apiBasePath: string;
  typeOptions?: readonly ProcessLibraryTypeOption[];
  permissions: ProcessLibraryPermissions;
}

export const PROCESS_LIBRARY_TYPE_OPTIONS_MAP: Partial<Record<ProcessConfigModuleKey, readonly ProcessLibraryTypeOption[]>> = {
  materials: [
    { label: '\u9ed1\u7c89\u539f\u6599', value: 'battery_black_mass' },
    { label: '\u539f\u6599', value: 'raw_material' },
  ],
  products: [
    { label: '\u4ea7\u54c1', value: 'product' },
    { label: '\u526f\u4ea7\u7269', value: 'byproduct' },
    { label: '\u5e9f\u56fa', value: 'solid_waste' },
    { label: '\u5e9f\u6c34', value: 'wastewater' },
  ],
  consumables: [
    { label: '\u5316\u5b66\u54c1', value: 'chemical' },
    { label: '\u836f\u5242', value: 'reagent' },
  ],
  'public-services': [
    { label: '\u516c\u8f85', value: 'utility' },
    { label: '\u516c\u5171\u670d\u52a1', value: 'public_service' },
  ],
};

export function processLibraryTypeLabel(moduleKey: ProcessConfigModuleKey, type: string): string {
  return PROCESS_LIBRARY_TYPE_OPTIONS_MAP[moduleKey]?.find((item) => item.value === type)?.label || type || '-';
}

export function getProcessConfigModuleMeta(moduleKey: ProcessConfigModuleKey): ProcessConfigModuleMeta {
  return PROCESS_CONFIG_MODULE_META_MAP[moduleKey];
}

export function normalizeRegionPrices(regionPrices: ProcessRegionPrice[] = [], unit = ''): ProcessRegionPrice[] {
  return PROCESS_REGION_DEFINITIONS.map((definition) => {
    const current = regionPrices.find((price) => price.region_code === definition.region_code);
    return {
      id: current?.id,
      owner_type: current?.owner_type,
      owner_id: current?.owner_id,
      region_code: definition.region_code,
      region_name: current?.region_name || definition.region_name,
      currency: current?.currency || definition.currency,
      unit_price: current?.unit_price ?? 0,
      unit: current?.unit || unit,
      status: current?.status || 'enabled',
      created_at: current?.created_at,
      updated_at: current?.updated_at,
    };
  });
}
