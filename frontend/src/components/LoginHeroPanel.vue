<!--
  登录页左侧品牌视觉组件

  负责：
  1. 绑定左侧整张品牌视觉图
  2. 以设计稿尺寸为基准做统一缩放，避免内部元素比例漂移
-->
<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue';

import loginHeroImage from '@/assets/login-hero-reference.png';

const DESIGN_WIDTH = 3028;
const DESIGN_HEIGHT = 2832;

const containerRef = ref<HTMLElement | null>(null);
const scale = ref(1);
const offsetX = ref(0);
const offsetY = ref(0);
let resizeObserver: ResizeObserver | null = null;

const stageStyle = computed(() => ({
  width: `${DESIGN_WIDTH}px`,
  height: `${DESIGN_HEIGHT}px`,
  transform: `translate(${offsetX.value}px, ${offsetY.value}px) scale(${scale.value})`,
}));

function updateScale(): void {
  const container = containerRef.value;
  if (!container) return;
  const { width, height } = container.getBoundingClientRect();
  if (!width || !height) return;

  // 使用 cover 缩放策略：整张设计稿等比缩放，覆盖左侧容器，多余部分由容器裁切。
  const nextScale = Math.min(width / DESIGN_WIDTH, height / DESIGN_HEIGHT);
  scale.value = nextScale;
  offsetX.value = (width - DESIGN_WIDTH * nextScale) / 2;
  offsetY.value = (height - DESIGN_HEIGHT * nextScale) / 2;
}

onMounted(() => {
  updateScale();
  resizeObserver = new ResizeObserver(updateScale);
  if (containerRef.value) {
    resizeObserver.observe(containerRef.value);
  }
});

onBeforeUnmount(() => {
  resizeObserver?.disconnect();
  resizeObserver = null;
});
</script>

<template>
  <section ref="containerRef" class="login-hero-panel" aria-label="Botree Knowledge OS 企业知识管理与智能体平台">
    <div class="hero-stage" :style="stageStyle">
      <img class="hero-image" :src="loginHeroImage" alt="" />
    </div>
  </section>
</template>

<style scoped>
.login-hero-panel {
  position: relative;
  min-width: 0;
  overflow: hidden;
  background: #eaf4ff;
}

.hero-stage {
  position: absolute;
  top: 0;
  left: 0;
  transform-origin: 0 0;
  will-change: transform;
}

.hero-image {
  display: block;
  width: 100%;
  height: 100%;
  user-select: none;
  pointer-events: none;
}
</style>
