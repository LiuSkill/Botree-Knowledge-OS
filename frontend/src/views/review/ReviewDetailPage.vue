<!--
  Review Detail Page

  负责：
  1. 展示单个审核任务详情
  2. 支持审核通过和驳回
  3. 跳转查看关联文档
-->
<script setup lang="ts">
import { MessagePlugin } from 'tdesign-vue-next';
import { computed, onMounted, ref } from 'vue';
import { useRoute, useRouter } from 'vue-router';

import { approveReviewTask, getReviewTask, rejectReviewTask } from '@/api/reviews';
import PageContainer from '@/components/PageContainer.vue';
import StatusTag from '@/components/StatusTag.vue';
import { PERMISSIONS } from '@/constants/permissions';
import { useAuthStore } from '@/stores/auth';
import type { ReviewTask } from '@/types/api';
import { isReviewTaskPending } from '@/utils/constants';
import { formatDateTime } from '@/utils/format';

const route = useRoute();
const router = useRouter();
const authStore = useAuthStore();
const task = ref<ReviewTask | null>(null);
const canApproveTask = computed(() => authStore.hasActionPermission(PERMISSIONS.REVIEW_APPROVE));
const canRejectTask = computed(() => authStore.hasActionPermission(PERMISSIONS.REVIEW_REJECT));

async function loadTask(): Promise<void> {
  /**
   * 加载审核任务详情。
   */
  task.value = await getReviewTask(Number(route.params.id));
}

async function decide(action: 'approve' | 'reject'): Promise<void> {
  /**
   * 执行审核动作。
   */
  if (!task.value) return;
  if (action === 'approve' && !canApproveTask.value) {
    MessagePlugin.warning('当前账号没有审核通过权限');
    return;
  }
  if (action === 'reject' && !canRejectTask.value) {
    MessagePlugin.warning('当前账号没有审核驳回权限');
    return;
  }
  task.value = action === 'approve' ? await approveReviewTask(task.value.id) : await rejectReviewTask(task.value.id);
  MessagePlugin.success('审核已处理');
}

onMounted(loadTask);
</script>

<template>
  <PageContainer title="审核详情" subtitle="查看资料审核状态和处理结果">
    <template #actions>
      <t-button variant="outline" @click="router.push('/reviews')">返回审核中心</t-button>
      <t-button v-permission="PERMISSIONS.REVIEW_APPROVE" theme="success" :disabled="!canApproveTask || !isReviewTaskPending(task?.review_status)" @click="decide('approve')">审核通过</t-button>
      <t-button v-permission="PERMISSIONS.REVIEW_REJECT" theme="danger" :disabled="!canRejectTask || !isReviewTaskPending(task?.review_status)" @click="decide('reject')">审核驳回</t-button>
    </template>

    <div v-if="task" class="review-detail-scroll data-scroll">
      <t-card>
      <div class="detail-grid">
        <div class="detail-item">
          <div class="detail-label">审核任务</div>
          <div class="detail-value">#{{ task.id }}</div>
        </div>
        <div class="detail-item">
          <div class="detail-label">关联文档</div>
          <div class="detail-value"><t-link theme="primary" @click="router.push(`/documents/${task.document_id}`)">文档 #{{ task.document_id }}</t-link></div>
        </div>
        <div class="detail-item">
          <div class="detail-label">审核状态</div>
          <div class="detail-value"><StatusTag type="review" :value="task.review_status" /></div>
        </div>
      </div>
      <p class="muted">创建时间：{{ formatDateTime(task.created_at) }}</p>
      <p>审核意见：{{ task.review_comment || '暂无意见' }}</p>
      </t-card>
    </div>
  </PageContainer>
</template>

<style scoped>
.review-detail-scroll {
  height: 100%;
}
</style>
