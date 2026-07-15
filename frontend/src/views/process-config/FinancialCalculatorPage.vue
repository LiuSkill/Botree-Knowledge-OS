<script setup lang="ts">
import {
  AddIcon,
  CalculatorIcon,
  ChartIcon,
  ChevronDownSIcon,
  ChevronUpSIcon,
  DeleteIcon,
  FileSearchIcon,
  MoneyIcon,
  RefreshIcon,
} from 'tdesign-icons-vue-next';
import { MessagePlugin } from 'tdesign-vue-next';
import { computed, onMounted, reactive, ref } from 'vue';
import { useRouter } from 'vue-router';

import { calculateProcessFinancialModel, getProcessCalculatorOptions } from '@/api/process-config';
import { PERMISSIONS } from '@/constants/permissions';
import RouteSchemeMindMap from '@/views/process-config/calculator/components/RouteSchemeMindMap.vue';
import type {
  CalculatorAmountItem,
  CalculatorMaterialInput,
  CalculatorSchemeSummary,
  CalculatorSortCriteria,
  DecimalValue,
  ProcessCalculatorOptions,
  ProcessCalculatorRequest,
  ProcessCalculatorResult,
} from '@/views/process-config/calculator/types';
import type { ProcessRegionCode, ProcessRegionCurrency } from '@/views/process-config/types';

interface MaterialFormRow {
  material_id?: number;
  amount: number;
  unit: string;
}

interface MetricItem {
  label: string;
  value: string;
  tone: 'default' | 'positive' | 'negative' | 'primary';
}

const permissions = {
  view: PERMISSIONS.PROCESS_CONFIG_CALCULATOR_VIEW,
  calculate: PERMISSIONS.PROCESS_CONFIG_CALCULATOR_CALCULATE,
  preview: PERMISSIONS.PROCESS_CONFIG_ROUTE_PREVIEW,
} as const;

const router = useRouter();
const optionsLoading = ref(false);
const calculating = ref(false);
const advancedVisible = ref(false);
const activeResultTab = ref('outputs');
const options = ref<ProcessCalculatorOptions | null>(null);
const result = ref<ProcessCalculatorResult | null>(null);
const expandedSchemeCodes = ref<Set<string>>(new Set());
const expansionInitialized = ref(false);

const form = reactive({
  materials: [{ amount: 5000, unit: 't' }] as MaterialFormRow[],
  targetProducts: [] as number[],
  regionCode: 'asia' as ProcessRegionCode,
  currency: 'CNY' as ProcessRegionCurrency,
  taxRatePercent: 25,
  discountRatePercent: 8,
  periodYears: 10,
  sortCriteria: 'npv' as CalculatorSortCriteria,
  baseCapacity: undefined as number | undefined,
  scaleParamN: undefined as number | undefined,
  otherOpex: 0,
  annualGrowthPercent: 0,
});

const totalProcessing = computed(() => form.materials.reduce((total, item) => total + numberValue(item.amount), 0));

const regionCurrencyOptions = computed(() =>
  (options.value?.regions || []).map((item) => ({
    label: `${item.name} · ${item.currency}`,
    value: item.code,
  })),
);

const sortCriteriaLabel = computed(() => {
  return options.value?.sort_criteria.find((item) => item.code === form.sortCriteria)?.name || '当前排序指标';
});

const headlineMetrics = computed<MetricItem[]>(() => {
  if (!result.value) return [];
  return [
    { label: '营业收入', value: formatMoney(result.value.revenue), tone: 'positive' },
    { label: '年度 OPEX', value: formatMoney(result.value.opex), tone: 'default' },
    {
      label: '年度 EBITDA',
      value: formatMoney(result.value.ebitda),
      tone: numberValue(result.value.ebitda) >= 0 ? 'positive' : 'negative',
    },
    { label: 'CAPEX', value: formatMoney(result.value.capex), tone: 'default' },
    {
      label: `NPV（${form.periodYears}年）`,
      value: formatMoney(result.value.npv),
      tone: numberValue(result.value.npv) >= 0 ? 'primary' : 'negative',
    },
    { label: 'IRR', value: formatPercent(result.value.irr), tone: 'positive' },
    { label: '静态回收期', value: formatYears(result.value.payback_period), tone: 'default' },
  ];
});

const recommendedMetrics = computed(() => result.value?.recommended_route?.metrics);

const opexBreakdown = computed(() => {
  const metrics = recommendedMetrics.value;
  if (!metrics) return [];
  return [
    { label: '原料成本', value: metrics.material_cost },
    { label: '药剂成本', value: metrics.consumable_cost },
    { label: '公辅成本', value: metrics.public_service_cost },
    { label: '三废处理', value: metrics.waste_treatment_cost },
    { label: '其他 OPEX', value: metrics.other_opex },
  ];
});

const maxOpexComponent = computed(() => Math.max(1, ...opexBreakdown.value.map((item) => numberValue(item.value))));

const warningSummary = computed(() => {
  const warnings = result.value?.warnings || [];
  const visible = warnings.slice(0, 5).join('；');
  return warnings.length > 5 ? `${visible}；另有 ${warnings.length - 5} 项请完善后台配置` : visible;
});

const amountColumns = [
  { colKey: 'name', title: '项目', minWidth: 180 },
  { colKey: 'output_type', title: '分类', width: 100 },
  { colKey: 'amount', title: '年数量', width: 150, align: 'right' as const },
  { colKey: 'unit_price', title: '区域单价', width: 150, align: 'right' as const },
  { colKey: 'cost', title: '年度金额', width: 170, align: 'right' as const },
];

const cashFlowColumns = [
  { colKey: 'year', title: '年度', width: 80, align: 'center' as const },
  { colKey: 'revenue', title: '收入', width: 160, align: 'right' as const },
  { colKey: 'opex', title: 'OPEX', width: 160, align: 'right' as const },
  { colKey: 'tax', title: '税额', width: 150, align: 'right' as const },
  { colKey: 'net_cash_flow', title: '净现金流', width: 170, align: 'right' as const },
  { colKey: 'discounted_cash_flow', title: '折现现金流', width: 180, align: 'right' as const },
];

onMounted(loadOptions);

async function loadOptions(): Promise<void> {
  optionsLoading.value = true;
  try {
    options.value = await getProcessCalculatorOptions();
    applyOptionDefaults();
  } finally {
    optionsLoading.value = false;
  }
}

function applyOptionDefaults(): void {
  if (!options.value) return;
  const defaults = options.value.defaults;
  form.taxRatePercent = numberValue(defaults.tax_rate) * 100;
  form.discountRatePercent = numberValue(defaults.discount_rate) * 100;
  form.periodYears = defaults.period_years;
  form.sortCriteria = defaults.sort_criteria;
}

function addMaterial(): void {
  if (form.materials.length >= 10) return;
  form.materials.push({ amount: 1000, unit: 't' });
}

function removeMaterial(index: number): void {
  if (form.materials.length === 1) return;
  form.materials.splice(index, 1);
}

function handleMaterialChange(row: MaterialFormRow): void {
  const material = options.value?.materials.find((item) => item.id === row.material_id);
  row.unit = normalizeMaterialUnit(material?.unit || 't');
}

function handleRegionChange(regionCode: ProcessRegionCode): void {
  const region = options.value?.regions.find((item) => item.code === regionCode);
  if (region) form.currency = region.currency;
}

async function handleCalculate(): Promise<void> {
  if (form.materials.some((item) => !item.material_id || item.amount <= 0)) {
    MessagePlugin.warning('请完整填写原料及处理量');
    return;
  }
  if (!form.targetProducts.length) {
    MessagePlugin.warning('请选择至少一个目标产品');
    return;
  }
  if ((form.baseCapacity === undefined) !== (form.scaleParamN === undefined)) {
    MessagePlugin.warning('基准产能和规模参数 n 必须同时填写');
    return;
  }
  calculating.value = true;
  try {
    result.value = await calculateProcessFinancialModel(buildPayload());
    activeResultTab.value = 'outputs';
    resetExpandedSchemes();
    MessagePlugin.success(`测算完成，已按${sortCriteriaLabel.value}保留前 ${result.value.matched_routes.length} 条路线`);
  } finally {
    calculating.value = false;
  }
}

function buildPayload(): ProcessCalculatorRequest {
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
    target_products: [...form.targetProducts],
    region_code: form.regionCode,
    currency: form.currency,
    tax_rate: form.taxRatePercent / 100,
    discount_rate: form.discountRatePercent / 100,
    period_years: form.periodYears,
    sort_criteria: form.sortCriteria,
    advanced_params: advancedParams,
  };
}

function resetCalculator(): void {
  form.materials.splice(0, form.materials.length, { amount: 5000, unit: 't' });
  form.targetProducts = [];
  form.regionCode = 'asia';
  form.currency = 'CNY';
  form.baseCapacity = undefined;
  form.scaleParamN = undefined;
  form.otherOpex = 0;
  form.annualGrowthPercent = 0;
  advancedVisible.value = false;
  result.value = null;
  expandedSchemeCodes.value = new Set();
  expansionInitialized.value = false;
  applyOptionDefaults();
}

function resetExpandedSchemes(): void {
  const firstScheme = result.value?.matched_routes[0];
  expandedSchemeCodes.value = firstScheme ? new Set([firstScheme.scheme_code]) : new Set();
  expansionInitialized.value = true;
}

function isSchemeExpanded(scheme: CalculatorSchemeSummary, index = -1): boolean {
  if (!expansionInitialized.value && index === 0) return true;
  return expandedSchemeCodes.value.has(scheme.scheme_code);
}

function toggleScheme(scheme: CalculatorSchemeSummary): void {
  expansionInitialized.value = true;
  const next = new Set(expandedSchemeCodes.value);
  if (next.has(scheme.scheme_code)) {
    next.delete(scheme.scheme_code);
  } else {
    next.add(scheme.scheme_code);
  }
  expandedSchemeCodes.value = next;
}

function previewScheme(row: CalculatorSchemeSummary): void {
  const routeId = row.routes[0]?.id;
  if (!routeId) return;
  const target = router.resolve({
    path: `/process-config/routes/${routeId}/preview`,
    query: { routes: row.routes.map((item) => item.id).join(',') },
  });
  window.open(target.href, '_blank', 'noopener,noreferrer');
}

function routeProducts(row: CalculatorSchemeSummary): string {
  return row.routes.map((route) => route.final_product_name).join('、');
}

function routeNames(row: CalculatorSchemeSummary): string {
  return row.routes.map((route) => route.name).join(' / ');
}

function opexBarWidth(value: DecimalValue): string {
  return `${Math.max(2, (numberValue(value) / maxOpexComponent.value) * 100)}%`;
}

function normalizeMaterialUnit(unit: string): string {
  const normalized = unit.trim().toLowerCase();
  return ['t', 'ton', '吨', 't-bm', 't/bm'].includes(normalized) ? 't' : unit;
}

function outputTypeLabel(type?: string | null): string {
  return (
    {
      product: '产品',
      byproduct: '副产品',
      solid_waste: '废固',
      wastewater: '废水',
    }[type || ''] || '-'
  );
}

function numberValue(value?: DecimalValue | null): number {
  const number = Number(value ?? 0);
  return Number.isFinite(number) ? number : 0;
}

function formatMoney(value?: DecimalValue | null): string {
  return `${new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 2 }).format(numberValue(value))} ${form.currency}`;
}

function formatAmount(value?: DecimalValue | null, unit = ''): string {
  return `${new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 6 }).format(numberValue(value))}${unit ? ` ${unit}` : ''}`;
}

function formatPercent(value?: DecimalValue | null): string {
  return value === null || value === undefined ? '-' : `${(numberValue(value) * 100).toFixed(2)}%`;
}

function formatYears(value?: DecimalValue | null): string {
  return value === null || value === undefined ? '-' : `${numberValue(value).toFixed(2)} 年`;
}
</script>

<template>
  <div v-permission="permissions.view" class="calculator-shell system-card">
    <aside class="input-pane">
      <div class="input-pane-header">
        <div>
          <h2>测算条件</h2>
          <span>年度口径</span>
        </div>
        <t-tooltip content="重置测算条件">
          <t-button shape="square" variant="text" theme="default" @click="resetCalculator">
            <RefreshIcon />
          </t-button>
        </t-tooltip>
      </div>

      <t-loading class="input-loading" :loading="optionsLoading" size="small">
        <div class="input-scroll">
          <section class="input-group">
            <div class="group-heading">
              <strong>原料输入</strong>
              <span>{{ formatAmount(totalProcessing, 't/a') }}</span>
            </div>
            <div class="material-list">
              <div v-for="(row, index) in form.materials" :key="index" class="material-row">
                <t-select
                  v-model="row.material_id"
                  filterable
                  placeholder="选择原料"
                  @change="handleMaterialChange(row)"
                >
                  <t-option
                    v-for="item in options?.materials || []"
                    :key="item.id"
                    :label="`${item.code} / ${item.name}`"
                    :value="item.id"
                  />
                </t-select>
                <t-input-number v-model="row.amount" :min="0.000001" :decimal-places="3" theme="normal" />
                <t-button
                  shape="square"
                  variant="text"
                  theme="danger"
                  title="删除原料"
                  :disabled="form.materials.length === 1"
                  @click="removeMaterial(index)"
                >
                  <DeleteIcon />
                </t-button>
              </div>
            </div>
            <t-button class="add-material-button" variant="dashed" block :disabled="form.materials.length >= 10" @click="addMaterial">
              <template #icon><AddIcon /></template>
              新增原料
            </t-button>
          </section>

          <section class="input-group">
            <div class="group-heading"><strong>目标产品</strong></div>
            <t-select v-model="form.targetProducts" multiple filterable clearable placeholder="选择一个或多个产品">
              <t-option
                v-for="item in options?.target_products || []"
                :key="item.id"
                :label="`${item.code} / ${item.name}`"
                :value="item.id"
              />
            </t-select>
          </section>

          <section class="input-group">
            <div class="group-heading"><strong>地区参数</strong></div>
            <t-radio-group
              v-model="form.regionCode"
              class="region-segment"
              theme="button"
              variant="default-filled"
              :options="regionCurrencyOptions"
              @change="handleRegionChange"
            />
          </section>

          <section class="input-group advanced-group">
            <button type="button" class="advanced-trigger" @click="advancedVisible = !advancedVisible">
              <strong>高级参数</strong>
              <ChevronUpSIcon v-if="advancedVisible" />
              <ChevronDownSIcon v-else />
            </button>
            <div v-if="advancedVisible" class="advanced-fields">
              <label><span>所得税率（%）</span><t-input-number v-model="form.taxRatePercent" :min="0" :max="100" :decimal-places="2" /></label>
              <label><span>折现率（%）</span><t-input-number v-model="form.discountRatePercent" :min="0" :max="100" :decimal-places="2" /></label>
              <label><span>测算周期（年）</span><t-input-number v-model="form.periodYears" :min="1" :max="50" /></label>
              <label><span>基准产能（t）</span><t-input-number v-model="form.baseCapacity" :min="0.000001" /></label>
              <label><span>规模参数 n</span><t-input-number v-model="form.scaleParamN" :min="0.000001" :max="1" :decimal-places="4" /></label>
              <label><span>其他年度 OPEX</span><t-input-number v-model="form.otherOpex" :min="0" :decimal-places="2" /></label>
              <label><span>年增长率（%）</span><t-input-number v-model="form.annualGrowthPercent" :min="-99" :max="100" :decimal-places="2" /></label>
            </div>
          </section>

          <section class="input-group sort-group">
            <div class="group-heading"><strong>路线排序指标</strong></div>
            <t-radio-group v-model="form.sortCriteria" direction="vertical">
              <t-radio v-for="item in options?.sort_criteria || []" :key="item.code" :value="item.code">
                {{ item.name }}
              </t-radio>
            </t-radio-group>
          </section>
        </div>
      </t-loading>

      <div class="calculate-action">
        <t-button
          v-permission="permissions.calculate"
          block
          theme="primary"
          size="large"
          :loading="calculating"
          @click="handleCalculate"
        >
          <template #icon><CalculatorIcon /></template>
          开始计算
        </t-button>
      </div>
    </aside>

    <main class="result-pane">
      <div v-if="!result" class="empty-result">
        <span class="empty-icon"><ChartIcon /></span>
        <strong>暂无测算结果</strong>
      </div>

      <template v-else>
        <section v-if="result.recommended_route" class="recommendation-band">
          <div class="recommendation-copy">
            <div class="recommendation-kicker">
              <MoneyIcon />
              <span>系统推荐最优路线</span>
              <t-tag theme="primary" variant="light">{{ sortCriteriaLabel }}</t-tag>
            </div>
            <strong>{{ routeProducts(result.recommended_route) }}</strong>
            <p>{{ routeNames(result.recommended_route) }}</p>
          </div>
          <div class="recommendation-value">
            <span>NPV（{{ form.periodYears }}年）</span>
            <strong>{{ formatMoney(result.npv) }}</strong>
          </div>
        </section>

        <section class="headline-metrics">
          <div v-for="item in headlineMetrics" :key="item.label" class="headline-metric" :class="`headline-metric--${item.tone}`">
            <span>{{ item.label }}</span>
            <strong>{{ item.value }}</strong>
          </div>
        </section>

        <t-alert
          v-if="result.warnings.length"
          class="configuration-alert"
          theme="warning"
          :title="`推荐路线有 ${result.warnings.length} 项配置提示`"
          :close="false"
        >
          {{ warningSummary }}
        </t-alert>

        <section class="route-section">
          <div class="section-heading">
            <div>
              <h2>工艺路线匹配</h2>
              <span>按{{ sortCriteriaLabel }}排序，最多展示 3 条</span>
            </div>
            <span class="route-count">{{ result.matched_routes.length }} 条路线</span>
          </div>

          <div class="route-grid">
            <article
              v-for="(scheme, index) in result.matched_routes"
              :key="scheme.scheme_code"
              class="route-card"
              :class="{ 'route-card--recommended': index === 0 }"
            >
              <header
                class="route-card-header"
                role="button"
                tabindex="0"
                @click="toggleScheme(scheme)"
                @keydown.enter.prevent="toggleScheme(scheme)"
                @keydown.space.prevent="toggleScheme(scheme)"
              >
                <div class="rank-badge">{{ index + 1 }}</div>
                <div class="route-title">
                  <div>
                    <strong>{{ routeProducts(scheme) }}</strong>
                    <t-tag v-if="index === 0" theme="success" variant="light" size="small">推荐</t-tag>
                  </div>
                  <span>{{ routeNames(scheme) }}</span>
                </div>
                <div class="route-actions">
                  <t-tooltip content="线路预览">
                    <t-button
                      v-permission="permissions.preview"
                      shape="square"
                      variant="text"
                      size="small"
                      @click.stop="previewScheme(scheme)"
                    >
                      <FileSearchIcon />
                    </t-button>
                  </t-tooltip>
                  <t-tooltip :content="isSchemeExpanded(scheme, index) ? '收起路线' : '展开路线'">
                    <t-button shape="square" variant="text" size="small" @click.stop="toggleScheme(scheme)">
                      <ChevronUpSIcon v-if="isSchemeExpanded(scheme, index)" />
                      <ChevronDownSIcon v-else />
                    </t-button>
                  </t-tooltip>
                </div>
              </header>

              <div v-if="isSchemeExpanded(scheme, index)" class="route-card-body">
                <RouteSchemeMindMap :scheme="scheme" />

                <div class="route-metrics">
                  <div><span>CAPEX</span><strong>{{ formatMoney(scheme.metrics.capex) }}</strong></div>
                  <div><span>OPEX</span><strong>{{ formatMoney(scheme.metrics.opex) }}</strong></div>
                  <div class="primary"><span>NPV</span><strong>{{ formatMoney(scheme.metrics.npv) }}</strong></div>
                  <div><span>IRR</span><strong>{{ formatPercent(scheme.metrics.irr) }}</strong></div>
                  <div><span>EBITDA</span><strong>{{ formatMoney(scheme.metrics.ebitda) }}</strong></div>
                  <div><span>回收期</span><strong>{{ formatYears(scheme.metrics.payback_period) }}</strong></div>
                </div>

                <div v-if="index === 0" class="route-detail-section">
                  <div class="section-heading detail-heading">
                    <div>
                      <h2>推荐路线测算明细</h2>
                      <span>{{ routeProducts(scheme) }}</span>
                    </div>
                  </div>

                  <t-tabs v-model="activeResultTab">
                    <t-tab-panel value="outputs" :label="`产品产出 (${result.product_outputs.length})`">
                      <t-table row-key="name" :data="result.product_outputs" :columns="amountColumns" stripe>
                        <template #output_type="{ row }">{{ outputTypeLabel(row.output_type) }}</template>
                        <template #amount="{ row }">{{ formatAmount(row.amount, row.unit) }}</template>
                        <template #unit_price="{ row }">{{ row.unit_price == null ? '-' : formatMoney(row.unit_price) }}</template>
                        <template #cost="{ row }">{{ formatMoney(row.cost) }}</template>
                      </t-table>
                    </t-tab-panel>

                    <t-tab-panel value="opex" label="OPEX 明细">
                      <div class="opex-layout">
                        <div class="opex-summary">
                          <div class="opex-summary-title">
                            <strong>年度运营成本构成</strong>
                            <span>{{ formatMoney(result.opex) }}</span>
                          </div>
                          <div v-for="item in opexBreakdown" :key="item.label" class="opex-row">
                            <div><span>{{ item.label }}</span><strong>{{ formatMoney(item.value) }}</strong></div>
                            <div class="opex-track"><i :style="{ width: opexBarWidth(item.value) }" /></div>
                          </div>
                        </div>
                        <div class="cost-tables">
                          <div>
                            <h3>药剂消耗</h3>
                            <t-table row-key="name" :data="result.consumable_costs" :columns="amountColumns" size="small" stripe>
                              <template #output_type>-</template>
                              <template #amount="{ row }">{{ formatAmount(row.amount, row.unit) }}</template>
                              <template #unit_price="{ row }">{{ row.unit_price == null ? '-' : formatMoney(row.unit_price) }}</template>
                              <template #cost="{ row }">{{ formatMoney(row.cost) }}</template>
                            </t-table>
                          </div>
                          <div>
                            <h3>公共服务</h3>
                            <t-table row-key="name" :data="result.public_service_costs" :columns="amountColumns" size="small" stripe>
                              <template #output_type>-</template>
                              <template #amount="{ row }">{{ formatAmount(row.amount, row.unit) }}</template>
                              <template #unit_price="{ row }">{{ row.unit_price == null ? '-' : formatMoney(row.unit_price) }}</template>
                              <template #cost="{ row }">{{ formatMoney(row.cost) }}</template>
                            </t-table>
                          </div>
                        </div>
                      </div>
                    </t-tab-panel>

                    <t-tab-panel value="waste" :label="`三废处理 (${result.waste_outputs.length})`">
                      <t-table row-key="name" :data="result.waste_outputs" :columns="amountColumns" stripe>
                        <template #output_type="{ row }"><span class="waste-type">{{ outputTypeLabel(row.output_type) }}</span></template>
                        <template #amount="{ row }">{{ formatAmount(row.amount, row.unit) }}</template>
                        <template #unit_price="{ row }">{{ row.unit_price == null ? '-' : formatMoney(row.unit_price) }}</template>
                        <template #cost="{ row }">{{ formatMoney(row.cost) }}</template>
                      </t-table>
                    </t-tab-panel>

                    <t-tab-panel value="balance" label="物料平衡">
                      <div v-if="result.material_balance" class="balance-grid">
                        <div><span>原料输入</span><strong>{{ formatAmount(result.material_balance.input_mass_t, 't') }}</strong></div>
                        <div><span>已核算产出</span><strong>{{ formatAmount(result.material_balance.accounted_output_mass_t, 't') }}</strong></div>
                        <div><span>平衡差额</span><strong>{{ formatAmount(result.material_balance.difference_mass_t, 't') }}</strong></div>
                        <div><span>平衡率</span><strong>{{ formatPercent(result.material_balance.balance_rate) }}</strong></div>
                      </div>
                    </t-tab-panel>

                    <t-tab-panel value="cashflow" label="年度现金流">
                      <t-table row-key="year" :data="result.cash_flows" :columns="cashFlowColumns" stripe>
                        <template #revenue="{ row }">{{ formatMoney(row.revenue) }}</template>
                        <template #opex="{ row }">{{ formatMoney(row.opex) }}</template>
                        <template #tax="{ row }">{{ formatMoney(row.tax) }}</template>
                        <template #net_cash_flow="{ row }">{{ formatMoney(row.net_cash_flow) }}</template>
                        <template #discounted_cash_flow="{ row }">{{ formatMoney(row.discounted_cash_flow) }}</template>
                      </t-table>
                    </t-tab-panel>
                  </t-tabs>
                </div>
              </div>

              <footer class="route-card-footer">
                <span>{{ scheme.node_codes.length }} 个工艺节点</span>
                <t-tag :theme="scheme.is_complete ? 'success' : 'warning'" variant="light" size="small">
                  {{ scheme.is_complete ? '配置完整' : `${scheme.warnings.length} 项提示` }}
                </t-tag>
              </footer>
            </article>
          </div>
        </section>

      </template>
    </main>
  </div>
</template>

<style scoped>
.calculator-shell {
  display: grid;
  grid-template-columns: 360px minmax(0, 1fr);
  border: 1px solid #dbe3ef;
  border-radius: 6px;
  background: #fff;
  overflow: hidden;
}

.input-pane,
.result-pane {
  min-width: 0;
  min-height: 0;
}

.input-pane {
  display: flex;
  flex-direction: column;
  border-right: 1px solid #dbe3ef;
  background: #fbfcfe;
}

.input-pane-header,
.section-heading,
.group-heading,
.route-card-header,
.route-card-footer,
.opex-summary-title {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.input-pane-header {
  min-height: 56px;
  padding: 0 16px;
  border-bottom: 1px solid #e7edf5;
  background: #fff;
}

.input-pane-header h2,
.section-heading h2 {
  display: inline;
  margin: 0;
  color: #172033;
  font-size: 15px;
  letter-spacing: 0;
}

.input-pane-header span,
.section-heading span {
  margin-left: 8px;
  color: #8290a5;
  font-size: 12px;
}

.input-loading {
  flex: 1 1 0;
  min-height: 0;
}

.input-loading :deep(.t-loading__parent) {
  height: 100%;
}

.input-scroll {
  height: 100%;
  overflow-x: hidden;
  overflow-y: auto;
  scrollbar-width: thin;
}

.input-group {
  padding: 16px;
  border-bottom: 1px solid #e7edf5;
}

.group-heading {
  margin-bottom: 10px;
}

.group-heading strong,
.advanced-trigger strong {
  color: #344258;
  font-size: 13px;
}

.group-heading span {
  color: #276ef1;
  font-size: 12px;
  font-weight: 600;
}

.material-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.material-row {
  display: grid;
  grid-template-columns: minmax(130px, 1fr) 105px 32px;
  gap: 6px;
  align-items: center;
}

.add-material-button {
  margin-top: 8px;
}

.region-segment {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  width: 100%;
}

.region-segment :deep(.t-radio-button) {
  min-width: 0;
  padding: 0 6px;
}

.region-segment :deep(.t-radio-button__label) {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.advanced-group {
  padding-top: 0;
  padding-bottom: 0;
}

.advanced-trigger {
  display: flex;
  width: 100%;
  height: 48px;
  align-items: center;
  justify-content: space-between;
  border: 0;
  color: #8290a5;
  background: transparent;
  cursor: pointer;
}

.advanced-fields {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px 10px;
  padding-bottom: 16px;
}

.advanced-fields label {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 6px;
}

.advanced-fields label > span {
  color: #718096;
  font-size: 11px;
}

.sort-group :deep(.t-radio-group) {
  gap: 9px;
}

.calculate-action {
  flex: 0 0 auto;
  padding: 14px 16px;
  border-top: 1px solid #dbe3ef;
  background: #fff;
}

.result-pane {
  overflow-x: hidden;
  overflow-y: auto;
  background: #f7f9fc;
  scrollbar-width: thin;
}

.empty-result {
  display: flex;
  height: 100%;
  min-height: 320px;
  align-items: center;
  justify-content: center;
  flex-direction: column;
  gap: 12px;
  color: #94a3b8;
}

.empty-result strong {
  font-size: 14px;
  font-weight: 500;
}

.empty-icon {
  display: grid;
  width: 48px;
  height: 48px;
  place-items: center;
  border: 1px solid #cfdae8;
  border-radius: 50%;
  color: #5f7ea8;
  background: #fff;
  font-size: 24px;
}

.recommendation-band {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 24px;
  padding: 18px 20px;
  border-bottom: 1px solid #bfd3f7;
  background: #edf4ff;
}

.recommendation-copy {
  min-width: 0;
}

.recommendation-kicker {
  display: flex;
  align-items: center;
  gap: 7px;
  color: #1d4ed8;
  font-size: 12px;
  font-weight: 700;
}

.recommendation-copy > strong {
  display: block;
  margin-top: 9px;
  color: #172033;
  font-size: 18px;
  letter-spacing: 0;
}

.recommendation-copy p {
  margin: 4px 0 0;
  color: #66758a;
  font-size: 12px;
}

.recommendation-value {
  flex: 0 0 auto;
  text-align: right;
}

.recommendation-value span {
  display: block;
  color: #63738b;
  font-size: 11px;
}

.recommendation-value strong {
  display: block;
  margin-top: 4px;
  color: #13795b;
  font-size: 22px;
  letter-spacing: 0;
}

.headline-metrics {
  display: grid;
  grid-template-columns: repeat(7, minmax(112px, 1fr));
  border-bottom: 1px solid #dbe3ef;
  background: #fff;
}

.headline-metric {
  min-width: 0;
  padding: 14px 13px;
  border-right: 1px solid #e7edf5;
}

.headline-metric:last-child {
  border-right: 0;
}

.headline-metric span,
.route-metrics span,
.balance-grid span {
  display: block;
  color: #728096;
  font-size: 11px;
}

.headline-metric strong {
  display: block;
  margin-top: 5px;
  overflow: hidden;
  color: #172033;
  font-size: 14px;
  letter-spacing: 0;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.headline-metric--positive strong { color: #13795b; }
.headline-metric--negative strong { color: #c53b3b; }
.headline-metric--primary strong { color: #1d4ed8; }

.configuration-alert {
  margin: 14px 18px 0;
}

.route-section {
  margin: 14px 18px 0;
  border: 1px solid #dbe3ef;
  border-radius: 6px;
  background: #fff;
}

.route-section {
  padding: 16px;
}

.section-heading {
  gap: 16px;
  margin-bottom: 14px;
}

.route-count {
  margin: 0 !important;
  padding: 4px 8px;
  border-radius: 4px;
  color: #1d4ed8 !important;
  background: #edf4ff;
  font-weight: 600;
}

.route-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: 12px;
}

.route-card {
  min-width: 0;
  border: 1px solid #dbe3ef;
  border-radius: 6px;
  background: #fff;
  overflow: hidden;
}

.route-card--recommended {
  border-color: #79a7f5;
  box-shadow: inset 0 3px 0 #276ef1;
}

.route-card-header {
  gap: 9px;
  padding: 13px 13px 10px;
  cursor: pointer;
  user-select: none;
}

.route-card-header:focus-visible {
  outline: 2px solid #276ef1;
  outline-offset: -2px;
}

.rank-badge {
  display: grid;
  width: 24px;
  height: 24px;
  flex: 0 0 24px;
  place-items: center;
  border-radius: 4px;
  color: #526176;
  background: #eef2f7;
  font-size: 12px;
  font-weight: 700;
}

.route-card--recommended .rank-badge {
  color: #fff;
  background: #276ef1;
}

.route-title {
  min-width: 0;
  flex: 1 1 auto;
}

.route-title > div {
  display: flex;
  min-width: 0;
  align-items: center;
  gap: 6px;
}

.route-title strong {
  overflow: hidden;
  color: #172033;
  font-size: 13px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.route-title > span {
  display: block;
  margin-top: 3px;
  overflow: hidden;
  color: #8290a5;
  font-size: 11px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.route-actions {
  display: flex;
  flex: 0 0 auto;
  align-items: center;
  gap: 4px;
}

.route-card-body {
  border-top: 1px solid #edf1f6;
  background: #fafbfd;
}

.route-card-body :deep(.scheme-tree-map) {
  padding: 12px;
  overflow-x: auto;
  overflow-y: hidden;
  background: #fafbfd;
  scrollbar-width: thin;
}

.route-card-body :deep(.scheme-tree-canvas) {
  min-width: 100%;
  position: relative;
}

.route-card-body :deep(.scheme-tree-lines) {
  position: absolute;
  inset: 0;
  pointer-events: none;
}

.route-card-body :deep(.scheme-tree-lines path) {
  fill: none;
  stroke: #b9c8db;
  stroke-width: 1;
  vector-effect: non-scaling-stroke;
}

.route-card-body :deep(.scheme-tree-node) {
  display: flex;
  width: 136px;
  min-height: 42px;
  flex-direction: column;
  justify-content: center;
  padding: 5px 9px;
  border: 1px solid #9db9df;
  border-radius: 4px;
  color: #27496f;
  background: #fff;
  box-sizing: border-box;
  position: absolute;
  top: 0;
  left: 0;
  z-index: 1;
}

.route-card-body :deep(.scheme-tree-node-name) {
  overflow: hidden;
  font-size: 12px;
  font-weight: 600;
  line-height: 17px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.route-card-body :deep(.scheme-tree-node-code) {
  margin-top: 1px;
  color: #7790ad;
  font-size: 10px;
  line-height: 14px;
}

.route-card-body :deep(.scheme-tree-node--material) {
  border-color: #276ef1;
  color: #1652b8;
  background: #edf4ff;
  box-shadow: inset 3px 0 0 #276ef1;
}

.route-card-body :deep(.scheme-tree-node--product) {
  border-color: #e87979;
  color: #c93636;
  background: #fff6f6;
  box-shadow: inset 3px 0 0 #e05252;
}

.route-card-body :deep(.scheme-tree-node--product .scheme-tree-node-code) {
  color: #cb6b6b;
}

.route-metrics {
  display: grid;
  grid-template-columns: repeat(6, minmax(0, 1fr));
  gap: 1px;
  background: #e8edf4;
}

.route-metrics > div {
  min-width: 0;
  padding: 9px 10px;
  background: #fff;
}

.route-metrics strong {
  display: block;
  margin-top: 4px;
  overflow: hidden;
  color: #344258;
  font-size: 11px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.route-metrics .primary {
  background: #f2f7ff;
}

.route-metrics .primary span,
.route-metrics .primary strong {
  color: #1d4ed8;
}

.route-card-footer {
  padding: 9px 12px;
  border-top: 1px solid #edf1f6;
  color: #728096;
  font-size: 11px;
}

.route-detail-section {
  margin: 12px;
  border: 1px solid #dbe3ef;
  border-radius: 6px;
  background: #fff;
  overflow: hidden;
}

.detail-heading {
  min-height: 52px;
  margin: 0;
  padding: 0 16px;
  border-bottom: 1px solid #e7edf5;
}

.route-detail-section :deep(.t-tabs__nav-container) {
  padding: 0 14px;
}

.route-detail-section :deep(.t-tabs__content) {
  padding: 0;
}

.opex-layout {
  display: grid;
  grid-template-columns: 280px minmax(0, 1fr);
  min-height: 280px;
}

.opex-summary {
  padding: 18px;
  border-right: 1px solid #e7edf5;
  background: #fbfcfe;
}

.opex-summary-title {
  margin-bottom: 18px;
}

.opex-summary-title strong,
.cost-tables h3 {
  margin: 0;
  color: #344258;
  font-size: 12px;
}

.opex-summary-title span {
  color: #172033;
  font-size: 12px;
  font-weight: 700;
}

.opex-row + .opex-row {
  margin-top: 14px;
}

.opex-row > div:first-child {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  color: #66758a;
  font-size: 11px;
}

.opex-row strong {
  color: #344258;
  font-size: 11px;
}

.opex-track {
  height: 5px;
  margin-top: 6px;
  border-radius: 3px;
  background: #e6ebf2;
  overflow: hidden;
}

.opex-track i {
  display: block;
  height: 100%;
  border-radius: 3px;
  background: #4f83dc;
}

.cost-tables {
  min-width: 0;
}

.cost-tables > div + div {
  border-top: 1px solid #e7edf5;
}

.cost-tables h3 {
  padding: 12px 14px;
}

.waste-type {
  color: #7c3aed;
  font-weight: 600;
}

.balance-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(150px, 1fr));
  gap: 1px;
  background: #e1e8f1;
}

.balance-grid > div {
  padding: 28px 22px;
  background: #fff;
}

.balance-grid strong {
  display: block;
  margin-top: 8px;
  color: #172033;
  font-size: 19px;
  letter-spacing: 0;
}

@media (max-width: 1500px) {
  .calculator-shell { grid-template-columns: 330px minmax(0, 1fr); }
  .headline-metrics { grid-template-columns: repeat(4, minmax(120px, 1fr)); }
  .headline-metric:nth-child(4) { border-right: 0; }
  .headline-metric:nth-child(n + 5) { border-top: 1px solid #e7edf5; }
  .route-grid { grid-template-columns: 1fr; }
}

@media (max-width: 1050px) {
  .calculator-shell { display: flex; flex-direction: column; overflow: auto; }
  .input-pane { flex: 0 0 auto; border-right: 0; border-bottom: 1px solid #dbe3ef; }
  .input-scroll { max-height: 520px; }
  .result-pane { flex: 0 0 auto; overflow: visible; }
  .headline-metrics, .balance-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .recommendation-band { align-items: flex-start; flex-direction: column; }
  .recommendation-value { text-align: left; }
  .opex-layout { grid-template-columns: 1fr; }
  .opex-summary { border-right: 0; border-bottom: 1px solid #e7edf5; }
}
</style>
