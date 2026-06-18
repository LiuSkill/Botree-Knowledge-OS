<!--
  Model Config Page

  负责：
  1. 展示 LLM 和 Embedding 模型配置
  2. 支持新增模型配置和设置默认模型
  3. 对接后端模型配置 API，避免前端硬编码模型参数
-->
<script setup lang="ts">
import { MessagePlugin } from 'tdesign-vue-next';
import { onMounted, reactive, ref } from 'vue';

import { createModelConfig, listModelConfigs, setDefaultModelConfig } from '@/api/modelConfigs';
import type { ModelConfig } from '@/types/api';

const configs = ref<ModelConfig[]>([]);
const dialogVisible = ref(false);
const form = reactive({ provider: '', model_name: '', api_base: '', api_key: '', model_type: 'llm', enabled: true });
const modelTypeOptions = [
  { value: 'llm', label: 'LLM' },
  { value: 'intent', label: '意图识别' },
  { value: 'planner', label: '检索规划' },
  { value: 'evidence_judge_fast', label: '证据判断 Flash' },
  { value: 'evidence_judge', label: '证据判断 Plus' },
  { value: 'answer_llm', label: '普通回答' },
  { value: 'vision_llm', label: '视觉回答' },
  { value: 'analysis_llm', label: '复杂分析' },
  { value: 'embedding', label: 'Embedding' },
];

async function loadConfigs(): Promise<void> {
  /**
   * 查询模型配置。
   */
  configs.value = await listModelConfigs();
}

async function handleCreate(): Promise<void> {
  /**
   * 新增模型配置。
   */
  await createModelConfig({ ...form });
  MessagePlugin.success('模型配置已创建');
  dialogVisible.value = false;
  Object.assign(form, { provider: '', model_name: '', api_base: '', api_key: '', model_type: 'llm', enabled: true });
  await loadConfigs();
}

async function handleSetDefault(config: ModelConfig): Promise<void> {
  /**
   * 将模型配置设为默认。
   */
  await setDefaultModelConfig(config.id);
  MessagePlugin.success('默认模型已更新');
  await loadConfigs();
}

onMounted(loadConfigs);
</script>

<template>
  <t-card title="模型配置" class="system-card">
    <template #actions>
      <t-button theme="primary" @click="dialogVisible = true">新增模型</t-button>
    </template>
    <table class="plain-table">
      <thead>
        <tr>
          <th>供应商</th>
          <th>模型</th>
          <th>类型</th>
          <th>API Base</th>
          <th>默认</th>
          <th>状态</th>
          <th>操作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="config in configs" :key="config.id">
          <td>{{ config.provider }}</td>
          <td>{{ config.model_name }}</td>
          <td>{{ config.model_type }}</td>
          <td>{{ config.api_base || '-' }}</td>
          <td>{{ config.is_default ? '是' : '否' }}</td>
          <td>{{ config.enabled ? '启用' : '停用' }}</td>
          <td><t-button size="small" variant="text" :disabled="config.is_default" @click="handleSetDefault(config)">设为默认</t-button></td>
        </tr>
      </tbody>
    </table>

    <t-dialog v-model:visible="dialogVisible" header="新增模型配置" width="620px" @confirm="handleCreate">
      <t-form :data="form" label-align="top">
        <t-form-item label="供应商"><t-input v-model="form.provider" /></t-form-item>
        <t-form-item label="模型名称"><t-input v-model="form.model_name" /></t-form-item>
        <t-form-item label="模型类型">
          <t-select v-model="form.model_type">
            <t-option v-for="option in modelTypeOptions" :key="option.value" :value="option.value" :label="option.label" />
          </t-select>
        </t-form-item>
        <t-form-item label="API Base"><t-input v-model="form.api_base" /></t-form-item>
        <t-form-item label="API Key"><t-input v-model="form.api_key" type="password" /></t-form-item>
      </t-form>
    </t-dialog>
  </t-card>
</template>

<style scoped>
.system-card {
  margin-top: 16px;
}
</style>
