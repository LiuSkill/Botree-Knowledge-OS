import type {
  CalculatorAmountItem,
  CalculatorMaterialInput,
  CalculatorTargetOutputCategoryOption,
  DecimalValue,
  ProcessCalculatorRequest,
  TargetOutputCategory,
} from '@/views/process-config/calculator/types';
import type { ProcessRegionCode, ProcessRegionCurrency } from '@/views/process-config/types';

export interface CalculatorPayloadFormState {
  materials: Array<{ material_id?: number; amount: number; unit: string }>;
  targetOutputCategories: TargetOutputCategory[];
  regionCode: ProcessRegionCode;
  currency: ProcessRegionCurrency;
  taxRatePercent: number;
  discountRatePercent: number;
  periodYears: number;
  sortCriteria: ProcessCalculatorRequest['sort_criteria'];
  baseCapacity?: number;
  scaleParamN?: number;
  otherOpex: number;
  annualGrowthPercent: number;
}

export interface OutputSummaryGroups {
  revenueOutputs: CalculatorAmountItem[];
  wasteOutputs: CalculatorAmountItem[];
}

export function targetCategorySelectOptions(
  categories: CalculatorTargetOutputCategoryOption[],
): Array<{ label: string; value: TargetOutputCategory }> {
  return categories.map((item) => ({ label: item.name, value: item.code }));
}

export function buildCalculatorPayload(form: CalculatorPayloadFormState): ProcessCalculatorRequest {
  const materials: CalculatorMaterialInput[] = form.materials.map((item) => ({
    material_id: item.material_id as number,
    amount: item.amount,
    unit: item.unit,
  }));
  const advancedParams: ProcessCalculatorRequest['advanced_params'] = {
    other_opex: form.otherOpex,
    annual_growth_rate: form.annualGrowthPercent / 100,
  };
  if (form.baseCapacity !== undefined && form.scaleParamN !== undefined) {
    advancedParams.base_capacity = form.baseCapacity;
    advancedParams.scale_param_n = form.scaleParamN;
  }
  return {
    materials,
    target_output_categories: [...form.targetOutputCategories],
    region_code: form.regionCode,
    currency: form.currency,
    tax_rate: form.taxRatePercent / 100,
    discount_rate: form.discountRatePercent / 100,
    period_years: form.periodYears,
    sort_criteria: form.sortCriteria,
    advanced_params: advancedParams,
  };
}

export function groupOutputSummary(items: CalculatorAmountItem[]): OutputSummaryGroups {
  const revenueTypes = new Set(['product', 'byproduct']);
  return {
    revenueOutputs: items.filter((item) => revenueTypes.has(item.output_type || '')),
    wasteOutputs: items.filter((item) => !revenueTypes.has(item.output_type || '')),
  };
}

export function noRouteReasonText(reason?: string | null, fallback = ''): string {
  return reason?.trim() || fallback;
}

export function numberValue(value?: DecimalValue | null): number {
  const number = Number(value ?? 0);
  return Number.isFinite(number) ? number : 0;
}
