<!--
  Role Manage Page

  负责：
  1. 展示角色卡片
  2. 支持新增角色
  3. 展示角色绑定的权限数量
-->
<script setup lang="ts">
import { MessagePlugin } from 'tdesign-vue-next';
import { onMounted, reactive, ref } from 'vue';

import { createRole, listRoles } from '@/api/roles';
import type { RoleInfo } from '@/types/api';

const roles = ref<RoleInfo[]>([]);
const dialogVisible = ref(false);
const form = reactive({ name: '', code: '', description: '' });

async function loadRoles(): Promise<void> {
  /**
   * 查询角色列表。
   */
  roles.value = await listRoles();
}

async function handleCreate(): Promise<void> {
  /**
   * 新增角色。
   */
  await createRole({ ...form, permission_ids: [] });
  MessagePlugin.success('角色已创建');
  dialogVisible.value = false;
  Object.assign(form, { name: '', code: '', description: '' });
  await loadRoles();
}

onMounted(loadRoles);
</script>

<template>
  <t-card title="角色管理" class="system-card">
    <template #actions>
      <t-button theme="primary" @click="dialogVisible = true">新建角色</t-button>
    </template>
    <div class="role-grid">
      <div v-for="role in roles" :key="role.id" class="role-card">
        <div class="role-title">
          <span>{{ role.name }}</span>
          <t-tag size="small" variant="light">{{ role.enabled ? '启用' : '停用' }}</t-tag>
        </div>
        <p class="muted">{{ role.description || '暂无描述' }}</p>
        <div class="muted mono">{{ role.code }}</div>
        <div class="role-footer">权限 {{ role.permissions?.length || 0 }} 项</div>
      </div>
    </div>

    <t-dialog v-model:visible="dialogVisible" header="新建角色" width="520px" @confirm="handleCreate">
      <t-form :data="form" label-align="top">
        <t-form-item label="角色名称"><t-input v-model="form.name" /></t-form-item>
        <t-form-item label="角色编码"><t-input v-model="form.code" /></t-form-item>
        <t-form-item label="描述"><t-textarea v-model="form.description" /></t-form-item>
      </t-form>
    </t-dialog>
  </t-card>
</template>

<style scoped>
.system-card {
  margin-top: 16px;
}

.role-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 16px;
}

.role-card {
  border: 1px solid #edf0f5;
  border-radius: 8px;
  padding: 16px;
}

.role-title,
.role-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.role-title {
  color: #111827;
  font-weight: 700;
}

.role-footer {
  margin-top: 16px;
  color: #6b7280;
  font-size: 13px;
}
</style>
