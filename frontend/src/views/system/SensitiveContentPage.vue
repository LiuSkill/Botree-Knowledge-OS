<!-- 敏感内容管理：沿用系统管理筛选区、列表、分页、弹窗和权限矩阵交互。 -->
<script setup lang="ts">
import {
  CheckCircleIcon, EditIcon, PoweroffIcon, RefreshIcon, SearchIcon, SettingIcon,
} from 'tdesign-icons-vue-next';
import { MessagePlugin } from 'tdesign-vue-next';
import { computed, onMounted, reactive, ref, watch } from 'vue';

import {
  getSensitivePermissionMatrix, listSensitiveAudits, listSensitiveRules, listSensitiveTypes,
  refreshSensitiveCache, saveSensitiveRolePermissions, saveSensitiveRule, saveSensitiveType,
  testSensitiveRule, type SensitiveAudit, type SensitiveRoleMatrix, type SensitiveRule, type SensitiveType,
} from '@/api/sensitiveContent';
import TableActionButton from '@/components/TableActionButton.vue';
import { useAuthStore } from '@/stores/auth';
import { formatDateTime } from '@/utils/format';

type TagTheme = 'default' | 'primary' | 'success' | 'warning' | 'danger';
interface PaginationInfo { current: number; pageSize: number }

const DEFAULT_PAGE_SIZE = 10;
const PAGE_SIZE_OPTIONS = [10, 20, 50];
const authStore = useAuthStore();
const tab = ref('types');
const loading = ref(false);
const auditLoading = ref(false);
const savingPermissions = ref(false);
const refreshingCache = ref(false);
const types = ref<SensitiveType[]>([]);
const rules = ref<SensitiveRule[]>([]);
const matrix = ref<SensitiveRoleMatrix>({ types: [], roles: [] });
const audits = ref<SensitiveAudit[]>([]);
const auditTotal = ref(0);
const typePage = ref(1);
const rulePage = ref(1);
const auditPage = ref(1);
const typePageSize = ref(DEFAULT_PAGE_SIZE);
const rulePageSize = ref(DEFAULT_PAGE_SIZE);
const auditPageSize = ref(DEFAULT_PAGE_SIZE);
const typeVisible = ref(false);
const ruleVisible = ref(false);
const testVisible = ref(false);
const typeSubmitting = ref(false);
const ruleSubmitting = ref(false);
const testingRule = ref(false);
const typeId = ref<number>();
const ruleId = ref<number>();
const dirtyRoleIds = ref(new Set<number>());
const dateRange = ref<string[]>([]);
const typeFilters = reactive({ keyword: '', enabled: '' });
const ruleFilters = reactive({ keyword: '', sensitive_type_code: '', match_type: '', enabled: '' });
const auditFilters = reactive({ user_id: undefined as number | undefined, sensitive_type: '', final_answer_redacted: '', chat_type: '', project_id: undefined as number | undefined });
const typeForm = reactive({ code: '', name: '', default_mask_text: '', enabled: true });
const ruleForm = reactive({ code: '', name: '', sensitive_type_code: '', match_type: 'keyword_window' as SensitiveRule['match_type'], pattern: '', keywords: '', window_size: 30, mask_text: '', priority: 100, enabled: true });
const testForm = reactive({ content: '', role_id: undefined as number | undefined, rule_id: undefined as number | undefined, rule_enabled: true });
const testResult = ref<{ safe_content: string; redacted: boolean; redaction_types: string[]; matched_rule_names: string[] }>();

const roleOptions = computed(() => matrix.value.roles.map((item) => ({ label: item.role_name, value: item.role_id })));
const typeOptions = computed(() => types.value.map((item) => ({ label: item.name, value: item.code })));
const ruleOptions = computed(() => rules.value.map((item) => ({ label: item.name, value: item.id })));
const typeNameMap = computed(() => new Map(types.value.map((item) => [item.code, item.name])));
const filteredTypes = computed(() => types.value.filter((item) => {
  const keyword = typeFilters.keyword.trim().toLowerCase();
  return (!keyword || item.name.toLowerCase().includes(keyword) || item.code.toLowerCase().includes(keyword))
    && (!typeFilters.enabled || item.enabled === (typeFilters.enabled === 'enabled'));
}));
const filteredRules = computed(() => rules.value.filter((item) => {
  const keyword = ruleFilters.keyword.trim().toLowerCase();
  return (!keyword || item.name.toLowerCase().includes(keyword) || item.code.toLowerCase().includes(keyword))
    && (!ruleFilters.sensitive_type_code || item.sensitive_type_code === ruleFilters.sensitive_type_code)
    && (!ruleFilters.match_type || item.match_type === ruleFilters.match_type)
    && (!ruleFilters.enabled || item.enabled === (ruleFilters.enabled === 'enabled'));
}));
const visibleTypes = computed(() => filteredTypes.value.slice((typePage.value - 1) * typePageSize.value, typePage.value * typePageSize.value));
const visibleRules = computed(() => filteredRules.value.slice((rulePage.value - 1) * rulePageSize.value, rulePage.value * rulePageSize.value));

const typeColumns = [
  { colKey: 'name', title: '类型名称', width: 160 }, { colKey: 'code', title: '编码', width: 170 },
  { colKey: 'default_mask_text', title: '默认脱敏文案', minWidth: 240, ellipsis: true },
  { colKey: 'enabled', title: '状态', width: 90 }, { colKey: 'updated_at', title: '更新时间', width: 170 },
  { colKey: 'operation', title: '操作', width: 110, fixed: 'right' },
];
const ruleColumns = [
  { colKey: 'name', title: '规则名称', minWidth: 170, ellipsis: true },
  { colKey: 'sensitive_type_code', title: '敏感类型', width: 140 },
  { colKey: 'match_type', title: '匹配方式', width: 130 },
  { colKey: 'pattern', title: '规则内容', minWidth: 230, ellipsis: true },
  { colKey: 'priority', title: '优先级', width: 90 }, { colKey: 'enabled', title: '状态', width: 90 },
  { colKey: 'operation', title: '操作', width: 110, fixed: 'right' },
];
const auditColumns = [
  { colKey: 'created_at', title: '时间', width: 170 }, { colKey: 'username', title: '用户', width: 140 },
  { colKey: 'role_names', title: '角色', minWidth: 160, ellipsis: true }, { colKey: 'chat_type', title: '问答类型', width: 110 },
  { colKey: 'project_name', title: '项目', minWidth: 150, ellipsis: true },
  { colKey: 'redaction_types', title: '脱敏类型', minWidth: 190 },
  { colKey: 'redaction_count', title: '次数', width: 80 },
  { colKey: 'final_answer_redacted', title: '最终答案兜底', width: 130 },
];

async function loadBaseData(): Promise<void> {
  if (!authStore.isAdmin) return;
  loading.value = true;
  try {
    [types.value, rules.value, matrix.value] = await Promise.all([
      listSensitiveTypes(), listSensitiveRules(), getSensitivePermissionMatrix(),
    ]);
    dirtyRoleIds.value = new Set();
  } finally { loading.value = false; }
}

function resetTypeFilters(): void { Object.assign(typeFilters, { keyword: '', enabled: '' }); typePage.value = 1; }
function resetRuleFilters(): void { Object.assign(ruleFilters, { keyword: '', sensitive_type_code: '', match_type: '', enabled: '' }); rulePage.value = 1; }
function editType(item?: SensitiveType): void {
  typeId.value = item?.id;
  Object.assign(typeForm, item ? { code: item.code, name: item.name, default_mask_text: item.default_mask_text, enabled: item.enabled } : { code: '', name: '', default_mask_text: '', enabled: true });
  typeVisible.value = true;
}
async function submitType(): Promise<void> {
  if (!typeForm.name.trim() || !typeForm.code.trim() || !typeForm.default_mask_text.trim()) { MessagePlugin.warning('请完整填写敏感类型信息'); return; }
  typeSubmitting.value = true;
  try { await saveSensitiveType({ ...typeForm }, typeId.value); typeVisible.value = false; await loadBaseData(); MessagePlugin.success('敏感类型已保存'); }
  finally { typeSubmitting.value = false; }
}
async function toggleType(item: SensitiveType): Promise<void> {
  await saveSensitiveType({ code: item.code, name: item.name, default_mask_text: item.default_mask_text, enabled: !item.enabled }, item.id);
  await loadBaseData(); MessagePlugin.success(item.enabled ? '敏感类型已停用' : '敏感类型已启用');
}
function editRule(item?: SensitiveRule): void {
  ruleId.value = item?.id;
  Object.assign(ruleForm, item ? { code: item.code, name: item.name, sensitive_type_code: item.sensitive_type_code, match_type: item.match_type, pattern: item.pattern, keywords: item.context_keywords.join('\n'), window_size: item.window_size, mask_text: item.mask_text || '', priority: item.priority, enabled: item.enabled } : { code: '', name: '', sensitive_type_code: types.value[0]?.code || '', match_type: 'keyword_window', pattern: '', keywords: '', window_size: 30, mask_text: '', priority: 100, enabled: true });
  ruleVisible.value = true;
}
async function submitRule(): Promise<void> {
  if (!ruleForm.name.trim() || !ruleForm.code.trim() || !ruleForm.sensitive_type_code || !ruleForm.pattern.trim()) { MessagePlugin.warning('请完整填写敏感规则信息'); return; }
  ruleSubmitting.value = true;
  try {
    const { keywords, ...form } = ruleForm;
    await saveSensitiveRule({ ...form, mask_text: form.mask_text || null, context_keywords: keywords.split(/[,，\n]/).map((value) => value.trim()).filter(Boolean) }, ruleId.value);
    ruleVisible.value = false; await loadBaseData(); MessagePlugin.success('敏感规则已保存');
  } finally { ruleSubmitting.value = false; }
}
async function toggleRule(item: SensitiveRule): Promise<void> {
  const { id: _id, version: _version, updated_at: _updatedAt, ...payload } = item;
  await saveSensitiveRule({ ...payload, enabled: !item.enabled }, item.id);
  await loadBaseData(); MessagePlugin.success(item.enabled ? '敏感规则已停用' : '敏感规则已启用');
}
async function runTest(): Promise<void> {
  if (!testForm.content.trim()) { MessagePlugin.warning('请输入测试文本'); return; }
  testingRule.value = true;
  try { testResult.value = await testSensitiveRule({ ...testForm }); }
  finally { testingRule.value = false; }
}
function openRuleTest(): void { testResult.value = undefined; testVisible.value = true; }
function markRoleDirty(roleId: number): void { dirtyRoleIds.value = new Set([...dirtyRoleIds.value, roleId]); }
async function savePermissions(): Promise<void> {
  if (!dirtyRoleIds.value.size) return;
  savingPermissions.value = true;
  try {
    for (const role of matrix.value.roles.filter((item) => dirtyRoleIds.value.has(item.role_id))) {
      await saveSensitiveRolePermissions(role.role_id, role.permissions);
    }
    await loadBaseData(); MessagePlugin.success('角色敏感权限已保存');
  } finally { savingPermissions.value = false; }
}
async function refreshCache(): Promise<void> {
  refreshingCache.value = true;
  try { await refreshSensitiveCache(); MessagePlugin.success('敏感规则缓存已刷新'); }
  finally { refreshingCache.value = false; }
}
function buildAuditParams() {
  return {
    page: auditPage.value, page_size: auditPageSize.value,
    started_at: dateRange.value[0] ? `${dateRange.value[0]}T00:00:00` : undefined,
    ended_at: dateRange.value[1] ? `${dateRange.value[1]}T23:59:59` : undefined,
    user_id: auditFilters.user_id, sensitive_type: auditFilters.sensitive_type || undefined,
    final_answer_redacted: auditFilters.final_answer_redacted ? auditFilters.final_answer_redacted === 'yes' : undefined,
    chat_type: auditFilters.chat_type || undefined, project_id: auditFilters.project_id,
  };
}
async function loadAudits(): Promise<void> {
  auditLoading.value = true;
  try { const result = await listSensitiveAudits(buildAuditParams()); audits.value = result.items; auditTotal.value = result.total; auditPage.value = result.page; auditPageSize.value = result.page_size; }
  finally { auditLoading.value = false; }
}
function searchAudits(): void { auditPage.value = 1; void loadAudits(); }
function resetAuditFilters(): void {
  Object.assign(auditFilters, { user_id: undefined, sensitive_type: '', final_answer_redacted: '', chat_type: '', project_id: undefined });
  dateRange.value = []; auditPage.value = 1; void loadAudits();
}
function handleTypePage(info: PaginationInfo): void { typePage.value = info.current; typePageSize.value = info.pageSize; }
function handleRulePage(info: PaginationInfo): void { rulePage.value = info.current; rulePageSize.value = info.pageSize; }
function handleAuditPage(info: PaginationInfo): void { auditPage.value = info.current; auditPageSize.value = info.pageSize; void loadAudits(); }
function statusTheme(enabled: boolean): TagTheme { return enabled ? 'success' : 'danger'; }
function matchTypeLabel(value: string): string { return ({ regex: '正则表达式', keyword: '关键词', keyword_window: '关键词窗口' } as Record<string, string>)[value] || value; }
function chatTypeLabel(value: string): string { return value === 'project_chat' ? '项目问答' : value === 'base_chat' ? '基础问答' : value; }

watch(tab, (value) => { if (value === 'audits' && !audits.value.length) void loadAudits(); });
watch([() => typeFilters.keyword, () => typeFilters.enabled], () => { typePage.value = 1; });
watch([() => ruleFilters.keyword, () => ruleFilters.sensitive_type_code, () => ruleFilters.match_type, () => ruleFilters.enabled], () => { rulePage.value = 1; });
onMounted(loadBaseData);
</script>

<template>
  <div v-if="authStore.isAdmin" class="system-card sensitive-card">
    <div class="page-actions">
      <span>规则或权限保存后会自动生效；必要时可手动刷新运行时缓存。</span>
      <t-button theme="default" variant="outline" :loading="refreshingCache" @click="refreshCache">
        <template #icon><RefreshIcon /></template>刷新缓存
      </t-button>
    </div>

    <t-tabs v-model="tab" class="management-tabs" :destroy-on-hide="false">
      <t-tab-panel value="types" label="敏感类型">
        <div class="tab-content">
          <t-form class="system-filter-form" layout="inline" label-align="left" label-width="auto">
            <t-form-item label="关键字"><t-input v-model="typeFilters.keyword" class="filter-input" clearable placeholder="类型名称 / 编码" /></t-form-item>
            <t-form-item label="状态"><t-select v-model="typeFilters.enabled" class="filter-select" clearable placeholder="全部状态"><t-option label="启用" value="enabled" /><t-option label="停用" value="disabled" /></t-select></t-form-item>
            <t-form-item><t-space><t-button theme="primary" @click="typePage = 1"><template #icon><SearchIcon /></template>查询</t-button><t-button @click="resetTypeFilters">重置</t-button></t-space></t-form-item>
          </t-form>
          <div class="system-section-head"><div class="system-section-title"><h2>敏感类型列表</h2><span>共 {{ filteredTypes.length }} 条数据</span></div><t-space><t-button theme="default" variant="outline" @click="loadBaseData"><template #icon><RefreshIcon /></template>刷新</t-button><t-button theme="primary" @click="editType()">新增敏感类型</t-button></t-space></div>
          <div class="table-scroll"><t-table row-key="id" bordered table-layout="fixed" :data="visibleTypes" :columns="typeColumns" :loading="loading" empty="暂无敏感类型">
            <template #default_mask_text="{ row }"><t-tooltip :content="row.default_mask_text"><div class="single-line">{{ row.default_mask_text }}</div></t-tooltip></template>
            <template #enabled="{ row }"><t-tag size="small" variant="light" :theme="statusTheme(row.enabled)">{{ row.enabled ? '启用' : '停用' }}</t-tag></template>
            <template #updated_at="{ row }">{{ formatDateTime(row.updated_at) }}</template>
            <template #operation="{ row }"><t-space size="small"><TableActionButton label="编辑" @click="editType(row)"><EditIcon /></TableActionButton><t-popconfirm :content="`确认${row.enabled ? '停用' : '启用'}该敏感类型？`" @confirm="toggleType(row)"><TableActionButton :label="row.enabled ? '停用' : '启用'"><PoweroffIcon /></TableActionButton></t-popconfirm></t-space></template>
          </t-table></div>
          <div class="system-pagination"><t-pagination :current="typePage" :page-size="typePageSize" :total="filteredTypes.length" :page-size-options="PAGE_SIZE_OPTIONS" show-jumper @change="handleTypePage" /></div>
        </div>
      </t-tab-panel>

      <t-tab-panel value="rules" label="敏感规则">
        <div class="tab-content">
          <t-form class="system-filter-form" layout="inline" label-align="left" label-width="auto">
            <t-form-item label="关键字"><t-input v-model="ruleFilters.keyword" class="filter-input" clearable placeholder="规则名称 / 编码" /></t-form-item>
            <t-form-item label="敏感类型"><t-select v-model="ruleFilters.sensitive_type_code" class="filter-select wide-select" clearable :options="typeOptions" placeholder="全部类型" /></t-form-item>
            <t-form-item label="匹配方式"><t-select v-model="ruleFilters.match_type" class="filter-select" clearable placeholder="全部方式"><t-option label="正则表达式" value="regex" /><t-option label="关键词" value="keyword" /><t-option label="关键词窗口" value="keyword_window" /></t-select></t-form-item>
            <t-form-item label="状态"><t-select v-model="ruleFilters.enabled" class="filter-select" clearable placeholder="全部状态"><t-option label="启用" value="enabled" /><t-option label="停用" value="disabled" /></t-select></t-form-item>
            <t-form-item><t-space><t-button theme="primary" @click="rulePage = 1">查询</t-button><t-button @click="resetRuleFilters">重置</t-button></t-space></t-form-item>
          </t-form>
          <div class="system-section-head"><div class="system-section-title"><h2>敏感规则列表</h2><span>共 {{ filteredRules.length }} 条数据</span></div><t-space><t-button theme="default" variant="outline" @click="openRuleTest"><template #icon><CheckCircleIcon /></template>规则测试</t-button><t-button theme="primary" @click="editRule()">新增敏感规则</t-button></t-space></div>
          <div class="table-scroll"><t-table row-key="id" bordered table-layout="fixed" :data="visibleRules" :columns="ruleColumns" :loading="loading" empty="暂无敏感规则">
            <template #sensitive_type_code="{ row }">{{ typeNameMap.get(row.sensitive_type_code) || row.sensitive_type_code }}</template>
            <template #match_type="{ row }"><t-tag size="small" variant="light">{{ matchTypeLabel(row.match_type) }}</t-tag></template>
            <template #pattern="{ row }"><t-tooltip :content="row.pattern"><div class="single-line rule-pattern">{{ row.pattern }}</div></t-tooltip></template>
            <template #enabled="{ row }"><t-tag size="small" variant="light" :theme="statusTheme(row.enabled)">{{ row.enabled ? '启用' : '停用' }}</t-tag></template>
            <template #operation="{ row }"><t-space size="small"><TableActionButton label="编辑" @click="editRule(row)"><EditIcon /></TableActionButton><t-popconfirm :content="`确认${row.enabled ? '停用' : '启用'}该敏感规则？`" @confirm="toggleRule(row)"><TableActionButton :label="row.enabled ? '停用' : '启用'"><PoweroffIcon /></TableActionButton></t-popconfirm></t-space></template>
          </t-table></div>
          <div class="system-pagination"><t-pagination :current="rulePage" :page-size="rulePageSize" :total="filteredRules.length" :page-size-options="PAGE_SIZE_OPTIONS" show-jumper @change="handleRulePage" /></div>
        </div>
      </t-tab-panel>

      <t-tab-panel value="permissions" label="角色敏感权限">
        <div class="tab-content">
          <div class="matrix-notice"><div><h2>角色敏感权限</h2><p>开关表示该角色可查看对应敏感类型；多角色用户按权限并集计算。</p></div><t-space><t-tag v-if="dirtyRoleIds.size" theme="warning" variant="light">{{ dirtyRoleIds.size }} 个角色有未保存修改</t-tag><t-button theme="primary" :disabled="!dirtyRoleIds.size" :loading="savingPermissions" @click="savePermissions"><template #icon><SettingIcon /></template>保存权限</t-button></t-space></div>
          <div class="matrix-scroll" v-loading="loading"><table><thead><tr><th class="sticky-role">角色</th><th v-for="item in matrix.types" :key="item.code">{{ item.name }}</th></tr></thead><tbody><tr v-for="role in matrix.roles" :key="role.role_id"><td class="sticky-role"><strong>{{ role.role_name }}</strong></td><td v-for="item in matrix.types" :key="item.code"><t-switch v-model="role.permissions[item.code]" @change="markRoleDirty(role.role_id)" /></td></tr></tbody></table><t-empty v-if="!matrix.roles.length && !loading" description="暂无角色权限数据" /></div>
        </div>
      </t-tab-panel>

      <t-tab-panel value="audits" label="脱敏审计">
        <div class="tab-content">
          <t-form class="system-filter-form audit-filter" layout="inline" label-align="left" label-width="auto">
            <t-form-item label="时间"><t-date-range-picker v-model="dateRange" class="filter-date-range" clearable value-type="YYYY-MM-DD" format="YYYY-MM-DD" separator="至" :placeholder="['开始日期', '结束日期']" /></t-form-item>
            <t-form-item label="用户"><t-input-number v-model="auditFilters.user_id" class="number-filter" clearable placeholder="用户ID" :min="1" /></t-form-item>
            <t-form-item label="敏感类型"><t-select v-model="auditFilters.sensitive_type" class="filter-select wide-select" clearable :options="typeOptions" placeholder="全部类型" /></t-form-item>
            <t-form-item label="最终兜底"><t-select v-model="auditFilters.final_answer_redacted" class="filter-select" clearable placeholder="全部"><t-option label="是" value="yes" /><t-option label="否" value="no" /></t-select></t-form-item>
            <t-form-item label="问答类型"><t-select v-model="auditFilters.chat_type" class="filter-select" clearable placeholder="全部类型"><t-option label="基础问答" value="base_chat" /><t-option label="项目问答" value="project_chat" /></t-select></t-form-item>
            <t-form-item label="项目"><t-input-number v-model="auditFilters.project_id" class="number-filter" clearable placeholder="项目ID" :min="1" /></t-form-item>
            <t-form-item><t-space><t-button theme="primary" :loading="auditLoading" @click="searchAudits">查询</t-button><t-button @click="resetAuditFilters">重置</t-button></t-space></t-form-item>
          </t-form>
          <div class="system-section-head"><div class="system-section-title"><h2>脱敏审计</h2><span>共 {{ auditTotal }} 条数据，仅展示安全元数据</span></div><t-button theme="default" variant="outline" @click="loadAudits"><template #icon><RefreshIcon /></template>刷新</t-button></div>
          <div class="table-scroll"><t-table row-key="id" bordered table-layout="fixed" vertical-align="top" :data="audits" :columns="auditColumns" :loading="auditLoading" empty="暂无脱敏审计记录">
            <template #created_at="{ row }">{{ formatDateTime(row.created_at) }}</template><template #username="{ row }">{{ row.username || (row.user_id ? `用户 #${row.user_id}` : '-') }}</template>
            <template #role_names="{ row }"><div class="single-line">{{ row.role_names.join('、') || '-' }}</div></template><template #chat_type="{ row }">{{ chatTypeLabel(row.chat_type) }}</template>
            <template #project_name="{ row }">{{ row.project_name || (row.project_id ? `项目 #${row.project_id}` : '-') }}</template>
            <template #redaction_types="{ row }"><t-space size="4px" break-line><t-tag v-for="item in row.redaction_types" :key="item" size="small" variant="light">{{ typeNameMap.get(item) || item }}</t-tag></t-space></template>
            <template #final_answer_redacted="{ row }"><t-tag size="small" variant="light" :theme="row.final_answer_redacted ? 'warning' : 'default'">{{ row.final_answer_redacted ? '是' : '否' }}</t-tag></template>
          </t-table></div>
          <div class="system-pagination"><t-pagination :current="auditPage" :page-size="auditPageSize" :total="auditTotal" :page-size-options="PAGE_SIZE_OPTIONS" show-jumper @change="handleAuditPage" /></div>
        </div>
      </t-tab-panel>
    </t-tabs>

    <t-dialog v-model:visible="typeVisible" :header="typeId ? '编辑敏感类型' : '新增敏感类型'" width="620px" :confirm-loading="typeSubmitting" @confirm="submitType">
      <t-form :data="typeForm" label-align="top"><t-form-item label="类型名称" required-mark><t-input v-model="typeForm.name" placeholder="请输入类型名称" /></t-form-item><t-form-item label="类型编码" required-mark><t-input v-model="typeForm.code" :disabled="Boolean(typeId)" placeholder="例如 price" /></t-form-item><t-form-item label="默认脱敏文案" required-mark><t-input v-model="typeForm.default_mask_text" placeholder="例如 [报价信息已隐藏]" /></t-form-item><t-form-item label="启用状态"><t-switch v-model="typeForm.enabled" /></t-form-item></t-form>
    </t-dialog>
    <t-dialog v-model:visible="ruleVisible" :header="ruleId ? '编辑敏感规则' : '新增敏感规则'" width="620px" :confirm-loading="ruleSubmitting" @confirm="submitRule">
      <t-form :data="ruleForm" label-align="top" class="dialog-scroll"><div class="form-grid"><t-form-item label="规则名称" required-mark><t-input v-model="ruleForm.name" /></t-form-item><t-form-item label="规则编码" required-mark><t-input v-model="ruleForm.code" :disabled="Boolean(ruleId)" /></t-form-item><t-form-item label="敏感类型" required-mark><t-select v-model="ruleForm.sensitive_type_code" :options="typeOptions" /></t-form-item><t-form-item label="匹配方式" required-mark><t-select v-model="ruleForm.match_type"><t-option label="正则表达式" value="regex" /><t-option label="关键词" value="keyword" /><t-option label="关键词窗口" value="keyword_window" /></t-select></t-form-item></div><t-form-item label="规则内容" required-mark><t-textarea v-model="ruleForm.pattern" :autosize="{ minRows: 3, maxRows: 6 }" placeholder="请输入正则表达式或关键词" /></t-form-item><t-form-item label="上下文关键词"><t-textarea v-model="ruleForm.keywords" :autosize="{ minRows: 2, maxRows: 4 }" placeholder="多个关键词使用换行或逗号分隔" /></t-form-item><div class="form-grid"><t-form-item label="上下文窗口"><t-input-number v-model="ruleForm.window_size" :min="0" :max="500" /></t-form-item><t-form-item label="优先级"><t-input-number v-model="ruleForm.priority" /></t-form-item></div><t-form-item label="脱敏文案"><t-input v-model="ruleForm.mask_text" placeholder="留空时使用敏感类型默认文案" /></t-form-item><t-form-item label="启用状态"><t-switch v-model="ruleForm.enabled" /></t-form-item></t-form>
    </t-dialog>
    <t-dialog v-model:visible="testVisible" width="620px" header="规则测试" :footer="false">
      <div class="test-description">输入用于验证规则的示例文本，结果仅在当前页面展示，不写入审计记录。</div>
      <t-form :data="testForm" label-align="top"><t-form-item label="测试文本" required-mark><t-textarea v-model="testForm.content" :autosize="{ minRows: 4, maxRows: 8 }" placeholder="请输入需要测试的文本" /></t-form-item><div class="form-grid"><t-form-item label="模拟角色"><t-select v-model="testForm.role_id" clearable :options="roleOptions" placeholder="默认无敏感查看权限" /></t-form-item><t-form-item label="指定规则"><t-select v-model="testForm.rule_id" clearable :options="ruleOptions" placeholder="默认测试全部规则" /></t-form-item></div><div class="test-actions"><t-switch v-model="testForm.rule_enabled" label="模拟规则启用" /><t-button theme="primary" :loading="testingRule" @click="runTest">执行测试</t-button></div></t-form>
      <div v-if="testResult" class="test-result"><div class="result-summary"><div><span>脱敏结果</span><t-tag size="small" variant="light" :theme="testResult.redacted ? 'warning' : 'success'">{{ testResult.redacted ? '已脱敏' : '未命中' }}</t-tag></div><div><span>命中类型</span><strong>{{ testResult.redaction_types.map((item) => typeNameMap.get(item) || item).join('、') || '无' }}</strong></div><div><span>命中规则</span><strong>{{ testResult.matched_rule_names.join('、') || '无' }}</strong></div></div><div class="safe-text"><span>安全文本</span><pre>{{ testResult.safe_content }}</pre></div></div>
    </t-dialog>
  </div>
  <div v-else class="system-card no-permission"><t-empty description="无权限访问敏感内容管理" /></div>
</template>

<style scoped>
.system-card { display:flex; flex:1 1 0; height:100%; min-height:0; min-width:0; flex-direction:column; overflow:hidden; }
.page-actions { display:flex; flex:0 0 auto; align-items:center; justify-content:space-between; gap:16px; margin-bottom:12px; color:#64748b; font-size:13px; }
.management-tabs { display:flex; flex:1 1 0; min-height:0; flex-direction:column; }
.management-tabs :deep(.t-tabs__content), .management-tabs :deep(.t-tab-panel), .management-tabs :deep(.t-tab-panel__content) { flex:1 1 0; height:100%; min-height:0; }
.management-tabs :deep(.t-tabs__content) { overflow:hidden; }
.tab-content { display:flex; height:100%; min-height:0; flex-direction:column; padding-top:16px; }
.system-filter-form { display:flex; flex:0 0 auto; flex-wrap:wrap; align-items:center; gap:12px 16px; margin-bottom:18px; border:1px solid #e5e7eb; border-radius:6px; background:#fff; padding:14px 16px; }
.system-filter-form :deep(.t-form__item) { margin:0; }
.system-filter-form :deep(.t-form__label) { width:auto!important; padding-right:8px; }
.system-filter-form :deep(.t-form__controls) { margin-left:0!important; }
.filter-input { width:220px; } .filter-select { width:132px; } .wide-select { width:160px; } .number-filter { width:128px; } .filter-date-range { width:260px; }
.system-section-head, .matrix-notice { display:flex; flex:0 0 auto; align-items:center; justify-content:space-between; gap:16px; margin-bottom:10px; }
.system-section-title { display:flex; align-items:baseline; gap:22px; }
.system-section-title h2, .matrix-notice h2 { margin:0; color:#0f172a; font-size:18px; font-weight:700; }
.system-section-title span, .matrix-notice p { margin:3px 0 0; color:#64748b; font-size:13px; }
.table-scroll, .matrix-scroll { flex:1 1 0; min-height:240px; border:1px solid #e5e7eb; border-radius:6px; background:#fff; overflow:auto; }
.table-scroll :deep(.t-table) { min-width:100%; }
.single-line { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; } .rule-pattern { color:#475569; font-family:ui-monospace,SFMono-Regular,Consolas,monospace; font-size:12px; }
.system-pagination { display:flex; flex:0 0 auto; align-items:center; justify-content:flex-end; min-height:48px; margin-top:12px; border-top:1px solid #edf2f7; background:#fff; padding-top:12px; }
.matrix-scroll table { width:max-content; min-width:100%; border-collapse:separate; border-spacing:0; }
.matrix-scroll th, .matrix-scroll td { min-width:138px; padding:13px 16px; border-right:1px solid #e5e7eb; border-bottom:1px solid #e5e7eb; text-align:center; white-space:nowrap; }
.matrix-scroll th { position:sticky; top:0; z-index:2; background:#f8fafc; color:#334155; font-weight:600; }
.matrix-scroll .sticky-role { position:sticky; left:0; z-index:3; min-width:180px; background:#fff; text-align:left; }
.matrix-scroll th.sticky-role { z-index:4; background:#f8fafc; }
.dialog-scroll { max-height:62vh; overflow:auto; padding-right:8px; }
.form-grid { display:grid; grid-template-columns:1fr 1fr; gap:0 16px; }
.test-description { margin-bottom:16px; border-radius:6px; background:#f3f6fa; padding:10px 12px; color:#64748b; font-size:13px; line-height:1.6; }
.test-actions { display:flex; align-items:center; justify-content:space-between; margin-top:4px; }
.test-result { margin-top:18px; border:1px solid #e5e7eb; border-radius:6px; overflow:hidden; }
.result-summary { display:grid; grid-template-columns:110px 1fr 1fr; gap:16px; background:#f8fafc; padding:14px 16px; }
.result-summary>div { display:flex; flex-direction:column; gap:6px; min-width:0; } .result-summary span, .safe-text>span { color:#64748b; font-size:12px; } .result-summary strong { overflow:hidden; color:#334155; font-size:13px; font-weight:500; text-overflow:ellipsis; white-space:nowrap; }
.safe-text { padding:14px 16px; } .safe-text pre { max-height:180px; margin:8px 0 0; overflow:auto; color:#334155; font-family:inherit; line-height:1.7; white-space:pre-wrap; word-break:break-word; }
.no-permission { align-items:center; justify-content:center; }
@media (max-width:1100px) { .page-actions,.matrix-notice { align-items:flex-start; flex-direction:column; } .form-grid,.result-summary { grid-template-columns:1fr; } .filter-input,.filter-select,.wide-select,.number-filter,.filter-date-range { width:100%; } }
</style>
