<!--
  Permission Matrix Page

  负责：
  1. 展示角色与权限点矩阵
  2. 帮助管理员审阅权限边界
  3. 为后续细粒度授权编辑预留界面
-->
<script setup lang="ts">
import { computed, onMounted, ref } from 'vue';

import { getPermissionMatrix } from '@/api/roles';
import type { PermissionInfo, RoleInfo } from '@/types/api';

const roles = ref<RoleInfo[]>([]);
const permissions = ref<PermissionInfo[]>([]);
const modules = computed(() => Array.from(new Set(permissions.value.map((item) => item.module))));

function roleHasPermission(role: RoleInfo, permission: PermissionInfo): boolean {
  /**
   * 判断角色是否包含指定权限。
   */
  return Boolean(role.permissions?.some((item) => item.id === permission.id));
}

async function loadMatrix(): Promise<void> {
  /**
   * 加载权限矩阵。
   */
  const result = await getPermissionMatrix();
  roles.value = result.roles;
  permissions.value = result.permissions;
}

onMounted(loadMatrix);
</script>

<template>
  <t-card title="权限矩阵" class="system-card">
    <div v-for="module in modules" :key="module" class="matrix-block">
      <h3>{{ module }}</h3>
      <table class="plain-table">
        <thead>
          <tr>
            <th>权限点</th>
            <th v-for="role in roles" :key="role.id">{{ role.name }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="permission in permissions.filter((item) => item.module === module)" :key="permission.id">
            <td>{{ permission.code }}</td>
            <td v-for="role in roles" :key="role.id">
              <t-tag size="small" :theme="roleHasPermission(role, permission) ? 'success' : 'default'" variant="light">
                {{ roleHasPermission(role, permission) ? '允许' : '未授权' }}
              </t-tag>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </t-card>
</template>

<style scoped>
.system-card {
  margin-top: 16px;
}

.matrix-block + .matrix-block {
  margin-top: 20px;
}

.matrix-block h3 {
  margin: 0 0 10px;
  font-size: 16px;
}
</style>
