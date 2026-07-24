<!--
  Project Form Drawer

  负责：
  1. 统一项目新建/编辑表单的抽屉交互。
  2. 按业务属性分区填写项目基础、客户状态、分类和交付信息。
-->
<script setup lang="ts">
import { MessagePlugin } from 'tdesign-vue-next';
import { computed, reactive, watch } from 'vue';

import type { ProjectPayload } from '@/api/projects';
import { useAuthStore } from '@/stores/auth';
import type { ProjectInfo, ProjectStatus, SecurityLevel } from '@/types/api';
import { clampSecurityLevel, securityLevelOptions } from '@/utils/securityLevels';

type ProjectFormMode = 'create' | 'edit';

interface ProjectFormState {
  project_name: string;
  project_code: string;
  project_short_name: string;
  customer_name: string;
  owner_name: string;
  project_status: ProjectStatus;
  security_level: SecurityLevel;
  description: string;
  project_english_name: string;
  project_type: string;
  project_stage: string;
  raw_material_type: string;
  capacity: string;
  process_route: string;
  main_products: string;
  scope_description: string;
  deliverables: string;
  progress: number;
}

const PROJECT_STATUS_OPTIONS: ProjectStatus[] = ['待启动', '进行中', '已完成', '已暂停'];

const props = withDefaults(
  defineProps<{
    visible: boolean;
    mode: ProjectFormMode;
    project?: ProjectInfo | null;
    saving?: boolean;
    showProgress?: boolean;
  }>(),
  {
    project: null,
    saving: false,
    showProgress: false,
  },
);

const emit = defineEmits<{
  'update:visible': [visible: boolean];
  submit: [payload: ProjectPayload];
}>();

const authStore = useAuthStore();

const drawerVisible = computed({
  get: () => props.visible,
  set: (visible: boolean) => emit('update:visible', visible),
});

const drawerTitle = computed(() => (props.mode === 'create' ? '新建项目' : '编辑项目'));
const submitText = computed(() => (props.mode === 'create' ? '创建项目' : '保存修改'));

const form = reactive<ProjectFormState>({
  project_name: '',
  project_code: '',
  project_short_name: '',
  customer_name: '',
  owner_name: '',
  project_status: '进行中',
  security_level: clampSecurityLevel('internal', authStore.maxSecurityLevel),
  description: '',
  project_english_name: '',
  project_type: '',
  project_stage: '',
  raw_material_type: '',
  capacity: '',
  process_route: '',
  main_products: '',
  scope_description: '',
  deliverables: '',
  progress: 0,
});

watch(
  () => [props.visible, props.mode, props.project] as const,
  ([visible]) => {
    if (visible) resetForm();
  },
  { immediate: true },
);

function resetForm(): void {
  const project = props.mode === 'edit' ? props.project : null;
  Object.assign(form, {
    project_name: project?.project_name || project?.name || '',
    project_code: project?.project_code || project?.code || '',
    project_short_name: project?.project_short_name || project?.name || '',
    customer_name: project?.customer_name || project?.client || '',
    owner_name: project?.owner_name || project?.manager || '',
    project_status: normalizeProjectStatus(project?.project_status || project?.status),
    security_level: project?.security_level || clampSecurityLevel('internal', authStore.maxSecurityLevel),
    description: project?.description || '',
    project_english_name: project?.project_english_name || '',
    project_type: project?.project_type || '',
    project_stage: project?.project_stage || '',
    raw_material_type: project?.raw_material_type || '',
    capacity: project?.capacity || '',
    process_route: project?.process_route || '',
    main_products: project?.main_products || '',
    scope_description: project?.scope_description || '',
    deliverables: project?.deliverables || '',
    progress: Number(project?.progress ?? 0),
  });
}

function normalizeProjectStatus(status?: string): ProjectStatus {
  if (status === '待启动' || status === '进行中' || status === '已完成' || status === '已暂停') return status;
  const legacyMap: Record<string, ProjectStatus> = {
    pending: '待启动',
    active: '进行中',
    completed: '已完成',
    archived: '已暂停',
    inactive: '已暂停',
  };
  return legacyMap[status || ''] || '进行中';
}

function buildProjectPayload(): ProjectPayload {
  return {
    project_name: form.project_name.trim(),
    project_code: form.project_code.trim(),
    project_short_name: form.project_short_name.trim(),
    customer_name: form.customer_name.trim(),
    owner_name: form.owner_name.trim(),
    project_status: form.project_status,
    security_level: form.security_level,
    description: form.description.trim(),
    project_english_name: form.project_english_name.trim(),
    project_type: form.project_type.trim(),
    project_stage: form.project_stage.trim(),
    raw_material_type: form.raw_material_type.trim(),
    capacity: form.capacity.trim(),
    process_route: form.process_route.trim(),
    main_products: form.main_products.trim(),
    scope_description: form.scope_description.trim(),
    deliverables: form.deliverables.trim(),
    progress: Number(form.progress) || 0,
  };
}

function validateProjectPayload(payload: ProjectPayload): boolean {
  // 必填项与后端项目基本信息规则保持一致，避免列表页和详情页校验分叉。
  const missing = [
    ['项目名称', payload.project_name],
    ['项目编号', payload.project_code],
    ['项目简称', payload.project_short_name],
    ['客户名称', payload.customer_name],
    ['项目负责人', payload.owner_name],
    ['项目状态', payload.project_status],
    ['项目密级', payload.security_level],
    ['项目简介', payload.description],
  ].filter(([, value]) => !String(value || '').trim());
  if (missing.length) {
    MessagePlugin.warning(`请补充：${missing.map(([label]) => label).join('、')}`);
    return false;
  }
  return true;
}

function closeDrawer(): void {
  if (props.saving) return;
  drawerVisible.value = false;
}

function submitForm(): void {
  const payload = buildProjectPayload();
  if (!validateProjectPayload(payload)) return;
  emit('submit', payload);
}
</script>

<template>
  <t-drawer
    v-model:visible="drawerVisible"
    class="project-form-drawer drawer-scroll"
    :close-on-esc-keydown="!props.saving"
    :close-on-overlay-click="!props.saving"
    destroy-on-close
    :header="drawerTitle"
    placement="right"
    size="min(840px, 96vw)"
  >
    <t-form :data="form" label-align="top" class="project-form">
      <section class="project-form-section">
        <div class="project-form-section-title">基础信息</div>
        <div class="project-form-grid">
          <t-form-item label="项目名称" required-mark><t-input v-model="form.project_name" /></t-form-item>
          <t-form-item label="项目编号" required-mark><t-input v-model="form.project_code" /></t-form-item>
          <t-form-item label="项目简称" required-mark><t-input v-model="form.project_short_name" /></t-form-item>
          <t-form-item label="英文名称"><t-input v-model="form.project_english_name" /></t-form-item>
        </div>
      </section>

      <section class="project-form-section">
        <div class="project-form-section-title">客户与状态</div>
        <div class="project-form-grid">
          <t-form-item label="客户名称" required-mark><t-input v-model="form.customer_name" /></t-form-item>
          <t-form-item label="项目负责人" required-mark><t-input v-model="form.owner_name" /></t-form-item>
          <t-form-item label="项目状态" required-mark>
            <t-select v-model="form.project_status">
              <t-option v-for="item in PROJECT_STATUS_OPTIONS" :key="item" :value="item" :label="item" />
            </t-select>
          </t-form-item>
          <t-form-item label="项目密级" required-mark>
            <t-select v-model="form.security_level">
              <t-option
                v-for="item in securityLevelOptions(authStore.maxSecurityLevel, form.security_level)"
                :key="item.value"
                :value="item.value"
                :label="item.label"
                :disabled="item.disabled"
              />
            </t-select>
          </t-form-item>
          <t-form-item v-if="props.showProgress && props.mode === 'edit'" label="项目进度">
            <t-input-number v-model="form.progress" class="progress-input" :min="0" :max="100" :step="1" suffix="%" theme="normal" />
          </t-form-item>
        </div>
      </section>

      <section class="project-form-section">
        <div class="project-form-section-title">项目分类</div>
        <div class="project-form-grid">
          <t-form-item label="项目类型"><t-input v-model="form.project_type" /></t-form-item>
          <t-form-item label="项目阶段"><t-input v-model="form.project_stage" /></t-form-item>
          <t-form-item label="原料类型"><t-input v-model="form.raw_material_type" /></t-form-item>
          <t-form-item label="处理能力"><t-input v-model="form.capacity" /></t-form-item>
        </div>
      </section>

      <section class="project-form-section">
        <div class="project-form-section-title">工艺与交付</div>
        <t-form-item label="项目简介" required-mark><t-textarea v-model="form.description" :autosize="{ minRows: 3, maxRows: 5 }" /></t-form-item>
        <t-form-item label="工艺路线"><t-textarea v-model="form.process_route" :autosize="{ minRows: 2, maxRows: 4 }" /></t-form-item>
        <t-form-item label="主要产品"><t-textarea v-model="form.main_products" :autosize="{ minRows: 2, maxRows: 4 }" /></t-form-item>
        <t-form-item label="项目范围"><t-textarea v-model="form.scope_description" :autosize="{ minRows: 2, maxRows: 4 }" /></t-form-item>
        <t-form-item label="交付成果"><t-textarea v-model="form.deliverables" :autosize="{ minRows: 2, maxRows: 4 }" /></t-form-item>
      </section>
    </t-form>

    <template #footer>
      <div class="project-form-drawer-footer">
        <t-button variant="outline" :disabled="props.saving" @click="closeDrawer">取消</t-button>
        <t-button theme="primary" :loading="props.saving" @click="submitForm">{{ submitText }}</t-button>
      </div>
    </template>
  </t-drawer>
</template>

<style scoped>
.project-form-drawer :deep(.t-drawer__body) {
  background: #f8fafc;
  padding: 18px;
}

.project-form {
  display: grid;
  gap: 16px;
}

.project-form-section {
  display: grid;
  gap: 12px;
  border: 1px solid #e6ebf2;
  border-radius: 6px;
  background: #fff;
  padding: 18px;
}

.project-form-section-title {
  color: #0f172a;
  font-size: 16px;
  font-weight: 800;
  line-height: 1.4;
}

.project-form-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0 16px;
}

.progress-input {
  width: 100%;
}

.project-form-drawer-footer {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
}

@media (max-width: 720px) {
  .project-form-drawer :deep(.t-drawer__body) {
    padding: 14px;
  }

  .project-form-section {
    padding: 14px;
  }

  .project-form-grid {
    grid-template-columns: 1fr;
  }
}
</style>
