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

const BUILTIN_CATEGORY_KEYS: Record<string, string> = {
  工艺技术: 'processTechnology',
  浸出工艺: 'leachingProcess',
  萃取分离: 'solventExtractionSeparation',
  沉淀结晶: 'precipitationCrystallization',
  电化学回收: 'electrochemicalRecovery',
  实验报告: 'experimentalReports',
  条件优化: 'conditionOptimization',
  表征分析: 'characterizationAnalysis',
  中试验证: 'pilotValidation',
  设计规范: 'designSpecifications',
  工艺设计: 'processDesign',
  设备选型: 'equipmentSelection',
  安全规范: 'safetySpecifications',
  标准法规: 'standardsRegulations',
  国家标准: 'nationalStandards',
  行业标准: 'industryStandards',
  环保法规: 'environmentalRegulations',
};

export function localizedCategoryName(name: string, translate: (key: string) => string): string {
  const key = BUILTIN_CATEGORY_KEYS[name.trim()];
  return key ? translate(`knowledge.category.builtin.${key}`) : name;
}

export function localizedCategoryPath(path: string, translate: (key: string) => string): string {
  return path
    .split(/(\s*[/>]\s*)/u)
    .map((part) => (/[/ >]/u.test(part) ? part : localizedCategoryName(part, translate)))
    .join('');
}

export function flattenCategories(categories: KnowledgeCategory[], level = 0): KnowledgeCategory[] {
  /**
   * 将分类树拍平成深度优先列表。
   */
  return categories.flatMap((category) => [category, ...flattenCategories(category.children || [], level + 1)]);
}

export function buildCategoryOptions(
  categories: KnowledgeCategory[],
  level = 0,
  labelResolver: (name: string) => string = (name) => name,
): CategoryOption[] {
  /**
   * 构建下拉框选项，使用缩进表达层级。
   */
  return categories.flatMap((category) => [
    {
      label: `${'　'.repeat(level)}${labelResolver(category.name)}`,
      value: category.id,
      disabled: !category.enabled,
    },
    ...buildCategoryOptions(category.children || [], level + 1, labelResolver),
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
