<script setup lang="ts">
import { computed } from 'vue';

import type {
  CalculatorRouteRef,
  CalculatorRouteTreeNodeKind,
  CalculatorSchemeSummary,
} from '@/views/process-config/calculator/types';

const NODE_WIDTH = 136;
const NODE_HEIGHT = 42;
const HORIZONTAL_GAP = 34;
const VERTICAL_GAP = 12;
const PADDING = 12;

const props = defineProps<{
  scheme: CalculatorSchemeSummary;
}>();

interface RouteTreeNode {
  key: string;
  segmentKey: string;
  code: string;
  label: string;
  kind: CalculatorRouteTreeNodeKind;
  children: RouteTreeNode[];
}

interface PositionedNode extends RouteTreeNode {
  depth: number;
  x: number;
  y: number;
}

interface TreeEdge {
  key: string;
  path: string;
}

function ensureChild(
  children: RouteTreeNode[],
  segmentKey: string,
  label: string,
  code: string,
  kind: CalculatorRouteTreeNodeKind,
  parentKey: string,
): RouteTreeNode {
  const existing = children.find((child) => child.segmentKey === segmentKey);
  if (existing) return existing;

  const child: RouteTreeNode = {
    key: `${parentKey}/${segmentKey}`,
    segmentKey,
    label,
    code,
    kind,
    children: [],
  };
  children.push(child);
  return child;
}

function appendRoute(roots: RouteTreeNode[], route: CalculatorRouteRef): void {
  const materialCode = route.input_material_code || String(route.input_material_id);
  let cursor = ensureChild(
    roots,
    `material:${materialCode}`,
    route.input_material_name,
    materialCode,
    'material',
    'root',
  );

  [...route.nodes]
    .sort((left, right) => left.sort_order - right.sort_order)
    .forEach((node) => {
      const nodeCode = node.code || String(node.id);
      cursor = ensureChild(cursor.children, `node:${nodeCode}`, node.name, nodeCode, 'node', cursor.key);
    });

  const productCode = route.final_product_code || String(route.final_product_id);
  ensureChild(
    cursor.children,
    `product:${productCode}`,
    route.final_product_name,
    productCode,
    'product',
    cursor.key,
  );
}

function buildTree(routes: CalculatorRouteRef[]): RouteTreeNode[] {
  const roots: RouteTreeNode[] = [];
  [...routes]
    .sort(
      (left, right) =>
        (left.final_product_code || '').localeCompare(right.final_product_code || '') ||
        (left.code || '').localeCompare(right.code || ''),
    )
    .forEach((route) => appendRoute(roots, route));
  return roots;
}

function buildLayout(roots: RouteTreeNode[]) {
  const nodes: PositionedNode[] = [];
  const edges: TreeEdge[] = [];
  let nextLeafY = PADDING;
  let maxDepth = 0;

  function visit(node: RouteTreeNode, depth: number): PositionedNode {
    maxDepth = Math.max(maxDepth, depth);
    const positioned = node as PositionedNode;
    positioned.depth = depth;
    positioned.x = PADDING + depth * (NODE_WIDTH + HORIZONTAL_GAP);

    if (!node.children.length) {
      positioned.y = nextLeafY;
      nextLeafY += NODE_HEIGHT + VERTICAL_GAP;
    } else {
      const childNodes = node.children.map((child) => visit(child, depth + 1));
      const firstChildCenter = childNodes[0].y + NODE_HEIGHT / 2;
      const lastChildCenter = childNodes[childNodes.length - 1].y + NODE_HEIGHT / 2;
      positioned.y = (firstChildCenter + lastChildCenter) / 2 - NODE_HEIGHT / 2;

      childNodes.forEach((child) => {
        const startX = positioned.x + NODE_WIDTH;
        const startY = positioned.y + NODE_HEIGHT / 2;
        const endX = child.x;
        const endY = child.y + NODE_HEIGHT / 2;
        const midX = startX + HORIZONTAL_GAP / 2;
        edges.push({
          key: `${positioned.key}->${child.key}`,
          path: `M ${startX} ${startY} H ${midX} V ${endY} H ${endX}`,
        });
      });
    }

    nodes.push(positioned);
    return positioned;
  }

  roots.forEach((root) => visit(root, 0));

  return {
    nodes,
    edges,
    width: PADDING * 2 + (maxDepth + 1) * NODE_WIDTH + maxDepth * HORIZONTAL_GAP,
    height: Math.max(NODE_HEIGHT + PADDING * 2, nextLeafY - VERTICAL_GAP + PADDING),
  };
}

const treeLayout = computed(() => buildLayout(buildTree(props.scheme.routes)));
</script>

<template>
  <div class="scheme-tree-map">
    <div
      class="scheme-tree-canvas"
      :style="{ width: `${treeLayout.width}px`, height: `${treeLayout.height}px` }"
    >
      <svg
        class="scheme-tree-lines"
        :width="treeLayout.width"
        :height="treeLayout.height"
        :viewBox="`0 0 ${treeLayout.width} ${treeLayout.height}`"
        aria-hidden="true"
      >
        <path v-for="edge in treeLayout.edges" :key="edge.key" :d="edge.path" />
      </svg>

      <div
        v-for="node in treeLayout.nodes"
        :key="node.key"
        class="scheme-tree-node"
        :class="`scheme-tree-node--${node.kind}`"
        :style="{ transform: `translate(${node.x}px, ${node.y}px)` }"
        :title="`${node.label} ${node.code}`"
      >
        <span class="scheme-tree-node-name">{{ node.label }}</span>
        <span class="scheme-tree-node-code">{{ node.code }}</span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.scheme-tree-map {
  padding: 12px;
  overflow-x: auto;
  overflow-y: hidden;
  background: #fafbfd;
  scrollbar-width: thin;
}

.scheme-tree-canvas {
  min-width: 100%;
  position: relative;
}

.scheme-tree-lines {
  position: absolute;
  inset: 0;
  pointer-events: none;
}

.scheme-tree-lines path {
  fill: none;
  stroke: #b9c8db;
  stroke-width: 1;
  vector-effect: non-scaling-stroke;
}

.scheme-tree-node {
  display: flex;
  width: 136px;
  min-height: 42px;
  flex-direction: column;
  justify-content: center;
  padding: 5px 9px;
  border: 1px solid #9db9df;
  border-radius: 4px;
  color: #27496f;
  background: #fff;
  box-sizing: border-box;
  position: absolute;
  top: 0;
  left: 0;
  z-index: 1;
}

.scheme-tree-node-name {
  overflow: hidden;
  font-size: 12px;
  font-weight: 600;
  line-height: 17px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.scheme-tree-node-code {
  margin-top: 1px;
  color: #7790ad;
  font-size: 10px;
  line-height: 14px;
}

.scheme-tree-node--material {
  border-color: #276ef1;
  color: #1652b8;
  background: #edf4ff;
  box-shadow: inset 3px 0 0 #276ef1;
}

.scheme-tree-node--product {
  border-color: #e87979;
  color: #c93636;
  background: #fff6f6;
  box-shadow: inset 3px 0 0 #e05252;
}

.scheme-tree-node--product .scheme-tree-node-code {
  color: #cb6b6b;
}
</style>
