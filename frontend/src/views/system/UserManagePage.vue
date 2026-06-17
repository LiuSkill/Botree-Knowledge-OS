<!--
  User Manage Page

  负责：
  1. 展示用户列表
  2. 支持管理员新增用户
  3. 管理用户基础资料和默认角色
-->
<script setup lang="ts">
import { MessagePlugin } from 'tdesign-vue-next';
import { onMounted, reactive, ref } from 'vue';

import { createUser, listUsers } from '@/api/users';
import type { UserInfo } from '@/types/api';

const users = ref<UserInfo[]>([]);
const dialogVisible = ref(false);
const form = reactive({ username: '', real_name: '', password: 'Botree@123456', email: '', department: '' });

async function loadUsers(): Promise<void> {
  /**
   * 查询系统用户列表。
   */
  users.value = await listUsers();
}

async function handleCreate(): Promise<void> {
  /**
   * 创建用户并刷新列表。
   */
  await createUser({ ...form });
  MessagePlugin.success('用户已创建');
  dialogVisible.value = false;
  Object.assign(form, { username: '', real_name: '', password: 'Botree@123456', email: '', department: '' });
  await loadUsers();
}

onMounted(loadUsers);
</script>

<template>
  <t-card title="用户管理" class="system-card">
    <template #actions>
      <t-button theme="primary" @click="dialogVisible = true">新建用户</t-button>
    </template>
    <table class="plain-table">
      <thead>
        <tr>
          <th>用户名</th>
          <th>姓名</th>
          <th>部门</th>
          <th>邮箱</th>
          <th>角色</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="user in users" :key="user.id">
          <td>{{ user.username }}</td>
          <td>{{ user.real_name }}</td>
          <td>{{ user.department || '-' }}</td>
          <td>{{ user.email || '-' }}</td>
          <td>{{ user.roles.map((role) => role.name).join('、') || '-' }}</td>
        </tr>
      </tbody>
    </table>

    <t-dialog v-model:visible="dialogVisible" header="新建用户" width="520px" @confirm="handleCreate">
      <t-form :data="form" label-align="top">
        <t-form-item label="用户名"><t-input v-model="form.username" /></t-form-item>
        <t-form-item label="姓名"><t-input v-model="form.real_name" /></t-form-item>
        <t-form-item label="初始密码"><t-input v-model="form.password" type="password" /></t-form-item>
        <t-form-item label="邮箱"><t-input v-model="form.email" /></t-form-item>
        <t-form-item label="部门"><t-input v-model="form.department" /></t-form-item>
      </t-form>
    </t-dialog>
  </t-card>
</template>

<style scoped>
.system-card {
  margin-top: 16px;
}
</style>
