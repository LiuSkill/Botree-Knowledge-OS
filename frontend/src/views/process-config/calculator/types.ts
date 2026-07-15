import type { ProcessRegionCode, ProcessRegionCurrency } from '@/views/process-config/types';

export type CalculatorSortCriteria = 'npv' | 'irr' | 'ebitda' | 'payback_period' | 'capex';
export type DecimalValue = string | number;

export interface CalculatorLibraryOption {
  id: number;
  code: string;
  name: string;
  unit: string;
}

export interface CalculatorRegionOption {
  code: ProcessRegionCode;
  name: string;
  currency: ProcessRegionCurrency;
}

export interface ProcessCalculatorOptions {
  materials: CalculatorLibraryOption[];
  target_products: CalculatorLibraryOption[];
  regions: CalculatorRegionOption[];
  sort_criteria: Array<{ code: CalculatorSortCriteria; name: string }>;
  defaults: {
    tax_rate: DecimalValue;
    discount_rate: DecimalValue;
    period_years: number;
    sort_criteria: CalculatorSortCriteria;
  };
}

export interface CalculatorMaterialInput {
  material_id: number;
  amount: DecimalValue;
  unit: string;
}

export interface ProcessCalculatorRequest {
  materials: CalculatorMaterialInput[];
  target_products: number[];
  region_code: ProcessRegionCode;
  currency: ProcessRegionCurrency;
  tax_rate: DecimalValue;
  discount_rate: DecimalValue;
  period_years: number;
  sort_criteria: CalculatorSortCriteria;
  advanced_params: {
    base_capacity?: DecimalValue;
    scale_param_n?: DecimalValue;
    other_opex: DecimalValue;
    annual_growth_rate: DecimalValue;
  };
}

export interface CalculatorRouteNodeRef {
  id: number;
  code: string;
  name: string;
  version: string;
  sort_order: number;
}

export interface CalculatorRouteRef {
  id: number;
  code: string;
  name: string;
  input_material_id: number;
  input_material_code: string;
  input_material_name: string;
  final_product_id: number;
  final_product_code: string;
  final_product_name: string;
  node_codes: string[];
  nodes: CalculatorRouteNodeRef[];
}

export type CalculatorRouteTreeNodeKind = 'material' | 'node' | 'product';

export interface CalculatorRouteTreeNode {
  key: string;
  segmentKey: string;
  code: string;
  label: string;
  kind: CalculatorRouteTreeNodeKind;
  children: CalculatorRouteTreeNode[];
}

export interface CalculatorMetrics {
  capex: DecimalValue;
  material_cost: DecimalValue;
  consumable_cost: DecimalValue;
  public_service_cost: DecimalValue;
  waste_treatment_cost: DecimalValue;
  other_opex: DecimalValue;
  opex: DecimalValue;
  revenue: DecimalValue;
  ebitda: DecimalValue;
  npv: DecimalValue;
  irr?: DecimalValue | null;
  payback_period?: DecimalValue | null;
  discounted_payback_period?: DecimalValue | null;
}

export interface CalculatorSchemeSummary {
  scheme_code: string;
  routes: CalculatorRouteRef[];
  node_codes: string[];
  is_complete: boolean;
  warnings: string[];
  metrics: CalculatorMetrics;
}

export interface CalculatorAmountItem {
  id?: number | null;
  code?: string | null;
  name: string;
  output_type?: string | null;
  amount: DecimalValue;
  unit: string;
  unit_price?: DecimalValue | null;
  cost: DecimalValue;
  route_id?: number | null;
  node_id?: number | null;
}

export interface CalculatorCashFlow {
  year: number;
  revenue: DecimalValue;
  opex: DecimalValue;
  tax: DecimalValue;
  net_cash_flow: DecimalValue;
  discounted_cash_flow: DecimalValue;
}

export interface CalculatorMaterialBalance {
  input_mass_t: DecimalValue;
  accounted_output_mass_t: DecimalValue;
  difference_mass_t: DecimalValue;
  balance_rate?: DecimalValue | null;
  excluded_non_mass_outputs: string[];
}

export interface ProcessCalculatorResult {
  calculation_id: string;
  matched_routes: CalculatorSchemeSummary[];
  recommended_route?: CalculatorSchemeSummary | null;
  product_outputs: CalculatorAmountItem[];
  consumable_costs: CalculatorAmountItem[];
  public_service_costs: CalculatorAmountItem[];
  waste_outputs: CalculatorAmountItem[];
  capex: DecimalValue;
  opex: DecimalValue;
  revenue: DecimalValue;
  ebitda: DecimalValue;
  npv: DecimalValue;
  irr?: DecimalValue | null;
  payback_period?: DecimalValue | null;
  material_balance?: CalculatorMaterialBalance | null;
  cash_flows: CalculatorCashFlow[];
  warnings: string[];
}
