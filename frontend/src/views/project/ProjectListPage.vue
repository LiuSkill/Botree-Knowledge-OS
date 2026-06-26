<!--
  Project List Page

  负责：
  1. 展示项目中心卡片列表
  2. 支持创建项目并自动生成项目知识库
  3. 进入项目详情维护项目资料和成员
-->
<script setup lang="ts">
import { MessagePlugin } from 'tdesign-vue-next';
import { onMounted, reactive, ref } from 'vue';
import { useRouter } from 'vue-router';

import { createProject, listProjects } from '@/api/projects';
import PageContainer from '@/components/PageContainer.vue';
import StatusTag from '@/components/StatusTag.vue';
import type { ProjectInfo, SecurityLevel } from '@/types/api';
import { SECURITY_LEVEL_OPTIONS, securityLevelLabel, securityLevelTheme } from '@/utils/securityLevels';

const router = useRouter();
const projects = ref<ProjectInfo[]>([]);
const dialogVisible = ref(false);
const form = reactive({
  name: '',
  code: '',
  client: '',
  manager: '',
  description: '',
  status: 'active',
  progress: 0,
  security_level: 'internal' as SecurityLevel,
});

async function loadProjects(): Promise<void> {
  /**
   * 查询当前用户可访问的项目。
   */
  projects.value = await listProjects();
}

async function handleCreate(): Promise<void> {
  /**
   * 创建项目并刷新项目卡片。
   */
  await createProject({ ...form });
  MessagePlugin.success('项目已创建，项目知识库已自动生成');
  dialogVisible.value = false;
  Object.assign(form, { name: '', code: '', client: '', manager: '', description: '', status: 'active', progress: 0, security_level: 'internal' });
  await loadProjects();
}

onMounted(loadProjects);
</script>

<template>
  <PageContainer title="项目中心" subtitle="项目资料、项目成员和项目知识库的隔离管理">
    <template #actions>
      <t-button v-permission="'project:create'" theme="primary" @click="dialogVisible = true">新建项目</t-button>
    </template>

    <div class="project-grid data-scroll">
      <t-card v-for="project in projects" :key="project.id" class="project-card" hover-shadow @click="router.push(`/projects/${project.id}`)">
        <div class="project-header">
          <div>
            <div class="project-name">{{ project.name }}</div>
            <div class="muted mono">{{ project.code }}</div>
          </div>
          <t-space size="small">
            <StatusTag type="project" :value="project.status" />
            <t-tag size="small" variant="light" :theme="securityLevelTheme(project.security_level)">
              {{ securityLevelLabel(project.security_level) }}
            </t-tag>
          </t-space>
        </div>
        <p class="project-desc">{{ project.description || '暂无项目描述' }}</p>
        <div class="project-meta">
          <span>客户：{{ project.client || '-' }}</span>
          <span>经理：{{ project.manager || '-' }}</span>
        </div>
        <t-progress :percentage="project.progress" theme="line" />
        <div class="project-footer">
          <span>{{ project.document_count }} 份资料</span>
          <span>{{ project.knowledge_count }} 个分块</span>
        </div>
      </t-card>
      <t-empty v-if="!projects.length" description="暂无项目，请先创建项目" />
    </div>

    <t-dialog v-model:visible="dialogVisible" header="新建项目" width="560px" @confirm="handleCreate">
      <t-form :data="form" label-align="top">
        <t-form-item label="项目名称"><t-input v-model="form.name" /></t-form-item>
        <t-form-item label="项目编码"><t-input v-model="form.code" /></t-form-item>
        <t-form-item label="客户名称"><t-input v-model="form.client" /></t-form-item>
        <t-form-item label="项目经理"><t-input v-model="form.manager" /></t-form-item>
        <t-form-item label="项目密级">
          <t-select v-model="form.security_level">
            <t-option v-for="item in SECURITY_LEVEL_OPTIONS" :key="item.value" :value="item.value" :label="item.label" />
          </t-select>
        </t-form-item>
        <t-form-item label="项目描述"><t-textarea v-model="form.description" /></t-form-item>
      </t-form>
    </t-dialog>
  </PageContainer>
</template>

<style scoped>
.project-grid {
  display: grid;
  height: 100%;
  min-height: 0;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  align-content: start;
  gap: 16px;
}

.project-card {
  cursor: pointer;
}

.project-header,
.project-footer,
.project-meta {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.project-name {
  color: #111827;
  font-size: 18px;
  font-weight: 700;
}

.project-desc {
  min-height: 46px;
  color: #4b5563;
  line-height: 1.7;
}

.project-meta,
.project-footer {
  color: #6b7280;
  font-size: 13px;
}
</style>
