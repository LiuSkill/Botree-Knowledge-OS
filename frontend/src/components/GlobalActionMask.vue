<!--
  GlobalActionMask

  负责：
  1. 在全局写操作期间提供统一遮罩
  2. 阻止重复点击触发多次提交
  3. 保持所有页面一致的交互反馈
-->
<script setup lang="ts">
import { useActionMask } from '@/stores/actionMask';

const { state } = useActionMask();
</script>

<template>
  <t-loading
    :loading="state.visible"
    fullscreen
    prevent-scroll-through
    :show-overlay="true"
    :text="state.text"
    :z-index="5000"
  />
</template>
