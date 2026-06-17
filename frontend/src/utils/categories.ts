/**
 * Category Utilities
 *
 * 负责：
 * 1. 将无限层级分类树转换为选择项
 * 2. 查询分类及其子孙分类 ID
 * 3. 避免页面内重复编写分类递归逻辑
 */

import type { KnowledgeCategory } from '@/types/api';

export interface CategoryOption {
  label: string;
  value: number;
  disabled?: boolean;
}

export function flattenCategories(categories: KnowledgeCategory[], level = 0): KnowledgeCategory[] {
  /**
   * 将分类树拍平成深度优先列表。
   */
  return categories.flatMap((category) => [category, ...flattenCategories(category.children || [], level + 1)]);
}

export function buildCategoryOptions(categories: KnowledgeCategory[], level = 0): CategoryOption[] {
  /**
   * 构建下拉框选项，使用缩进表达层级。
   */
  return categories.flatMap((category) => [
    {
      label: `${'　'.repeat(level)}${category.name}`,
      value: category.id,
      disabled: !category.enabled,
    },
    ...buildCategoryOptions(category.children || [], level + 1),
  ]);
}

export function collectCategoryIds(category: KnowledgeCategory | undefined): number[] {
  /**
   * 收集分类自身和全部子孙分类 ID。
   */
  if (!category) return [];
  return [category.id, ...(category.children || []).flatMap((child) => collectCategoryIds(child))];
}

export function findCategory(categories: KnowledgeCategory[], categoryId: number | null | undefined): KnowledgeCategory | undefined {
  /**
   * 在分类树中查找指定分类。
   */
  if (!categoryId) return undefined;
  for (const category of categories) {
    if (category.id === categoryId) return category;
    const child = findCategory(category.children || [], categoryId);
    if (child) return child;
  }
  return undefined;
}
