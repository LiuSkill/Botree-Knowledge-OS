import type { PermissionCode } from '@/constants/permissions';

export type ProcessLibraryStatus = 'enabled' | 'draft' | 'disabled';
export type ProcessRegionCode = 'asia' | 'europe' | 'americas';
export type ProcessRegionCurrency = 'CNY' | 'EUR' | 'USD';
export const PROCESS_CURRENCY_OPTIONS: readonly ProcessRegionCurrency[] = ['CNY', 'EUR', 'USD'];
export type ProcessConfigModuleKey =
  | 'materials'
  | 'products'
  | 'consumables'
  | 'public-services'
  | 'labor-costs'
  | 'equipment-assets'
  | 'infrastructure-assets'
  | 'nodes'
  | 'routes';

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
  'labor-costs': { key: 'labor-costs', label: '人员成本库', filenamePrefix: 'process-labor-costs' },
  'equipment-assets': { key: 'equipment-assets', label: '设备资产库', filenamePrefix: 'process-equipment-assets' },
  'infrastructure-assets': { key: 'infrastructure-assets', label: '基础设施库', filenamePrefix: 'process-infrastructure-assets' },
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
  salary_period?: 'month' | 'year';
  welfare_factor?: string | number;
  asset_class?: 'equipment' | 'infrastructure';
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
  salary_period?: 'month' | 'year';
  welfare_factor?: string | number;
  asset_class?: 'equipment' | 'infrastructure';
}

export interface ProcessLibraryListParams {
  keyword?: string;
  type?: string;
  status?: ProcessLibraryStatus;
  page?: number;
  page_size?: number;
  asset_class?: 'equipment' | 'infrastructure';
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
  fixedListParams?: Partial<ProcessLibraryListParams>;
  fixedPayload?: Partial<ProcessLibraryPayload>;
  enableImportExport?: boolean;
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
  'labor-costs': [
    { label: '生产人员', value: 'production' },
    { label: '生产管理人员', value: 'production_management' },
    { label: '管理人员', value: 'management' },
    { label: '工艺技术人员', value: 'engineering' },
    { label: '检维修人员', value: 'maintenance' },
    { label: '化验人员', value: 'laboratory' },
    { label: '安全环保人员', value: 'hse' },
  ],
  'equipment-assets': [
    { label: '反应设备', value: 'reactor' },
    { label: '反应/槽罐', value: 'reactor_tank' },
    { label: '泵阀管道', value: 'pump_valve_pipe' },
    { label: '分离过滤', value: 'separation_filter' },
    { label: '固液分离设备', value: 'solid_liquid_separation' },
    { label: '萃取设备', value: 'solvent_extraction' },
    { label: '结晶设备', value: 'crystallizer' },
    { label: '焙烧窑炉', value: 'kiln' },
    { label: '干燥设备', value: 'dryer' },
    { label: '蒸发设备', value: 'evaporator' },
    { label: '废气处理设备', value: 'off_gas_treatment' },
    { label: '干燥热工', value: 'drying_thermal' },
  ],
  'infrastructure-assets': [
    { label: '生产建筑', value: 'building' },
    { label: '仓库', value: 'warehouse' },
    { label: '办公及化验建筑', value: 'office_laboratory' },
    { label: '罐区', value: 'tank_farm' },
    { label: '循环冷却水系统', value: 'cooling_water' },
    { label: '空压及制氮系统', value: 'compressed_air_nitrogen' },
    { label: '变配电系统', value: 'power_distribution' },
    { label: '污水处理系统', value: 'wastewater_treatment' },
    { label: '土建', value: 'civil' },
    { label: '安装工程', value: 'installation' },
    { label: '仓储物流', value: 'warehouse_logistics' },
    { label: '环保安全', value: 'ehs' },
  ],
};

export function processLibraryTypeLabel(moduleKey: ProcessConfigModuleKey, type: string): string {
  return PROCESS_LIBRARY_TYPE_OPTIONS_MAP[moduleKey]?.find((item) => item.value === type)?.label || type || '-';
}

const PROCESS_UNIT_LABELS: Record<string, string> = {
  t: '吨', kg: '千克', g: '克', 't-BM': '吨黑粉', 't/t-BM': '吨/吨黑粉', 'kg/t-BM': '千克/吨黑粉',
  kWh: '千瓦时', 'kWh/t-BM': '千瓦时/吨黑粉', MWh: '兆瓦时', m3: '立方米', 'm3/t-BM': '立方米/吨黑粉',
  Nm3: '标准立方米', 'Nm3/t-BM': '标准立方米/吨黑粉', set: '套', m2: '平方米', person: '人', 'person-year': '人/年',
};

export const PROCESS_UNIT_OPTIONS = Object.entries(PROCESS_UNIT_LABELS).map(([value, label]) => ({ value, label }));

export function processUnitLabel(unit?: string | null): string {
  return unit ? PROCESS_UNIT_LABELS[unit] || unit : '-';
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
