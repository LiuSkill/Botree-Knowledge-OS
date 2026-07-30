import type { ProcessFormulaType, ProcessNodeType } from '@/views/process-config/node/types';
import type { ProcessLibraryStatus } from '@/views/process-config/types';

const PROCESS_NODE_TYPE_KEY_BY_VALUE: Record<ProcessNodeType, string> = {
  pretreatment: 'pretreatment',
  hydrometallurgy: 'hydrometallurgy',
  pyrometallurgy: 'pyrometallurgy',
  post_treatment: 'postTreatment',
};

const PROCESS_OUTPUT_TYPE_KEY_BY_VALUE: Record<string, string> = {
  product: 'product',
  byproduct: 'byproduct',
  solid_waste: 'solidWaste',
  wastewater: 'wastewater',
};

export function processStatusLocaleKey(status: ProcessLibraryStatus): string {
  return `process.status.${status}`;
}

export function processNodeTypeLocaleKey(value?: string | null): string | null {
  const key = PROCESS_NODE_TYPE_KEY_BY_VALUE[value as ProcessNodeType];
  return key ? `process.nodeType.${key}` : null;
}

export function processFormulaTypeLocaleKey(value?: ProcessFormulaType | string | null): string | null {
  return value === 'expression' || value === 'fixed' ? `process.formula.${value}` : null;
}

export function processOutputTypeLocaleKey(value?: string | null): string | null {
  const key = PROCESS_OUTPUT_TYPE_KEY_BY_VALUE[value || ''];
  return key ? `process.outputType.${key}` : null;
}
