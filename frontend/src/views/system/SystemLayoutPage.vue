<!--
  System Layout Page

  负责：
  1. 组织系统管理子页面导航
  2. 承载用户、角色、权限、日志、审计和模型配置
  3. 保持后台管理区域的统一布局
-->
<script setup lang="ts">
import { useRoute, useRouter } from 'vue-router';

const router = useRouter();
const route = useRoute();

const tabs = [
  { value: '/system/users', label: '用户管理' },
  { value: '/system/roles', label: '角色管理' },
  { value: '/system/permissions', label: '权限矩阵' },
  { value: '/system/model-configs', label: '模型配置' },
  { value: '/system/logs', label: '操作日志' },
  { value: '/system/qa-audits', label: '问答审计' },
];
</script>

<template>
  <div class="page">
    <div class="toolbar">
      <div>
        <h1 class="page-title">系统管理</h1>
        <p class="page-subtitle">用户、权限、模型、操作日志和问答审计</p>
      </div>
    </div>
    <t-card>
      <t-tabs :value="route.path" @change="(value) => router.push(String(value))">
        <t-tab-panel v-for="tab in tabs" :key="tab.value" :value="tab.value" :label="tab.label" />
      </t-tabs>
    </t-card>
    <router-view />
  </div>
</template>
