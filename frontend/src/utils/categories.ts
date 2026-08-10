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
  理论知识: 'theoreticalKnowledge',
  'Theoretical Knowledge': 'theoreticalKnowledge',
  工艺技术: 'processTechnology',
  'Process Technology': 'processTechnology',
  浸出工艺: 'leachingProcess',
  'Leaching Process': 'leachingProcess',
  萃取分离: 'solventExtractionSeparation',
  'Solvent Extraction Separation': 'solventExtractionSeparation',
  沉淀结晶: 'precipitationCrystallization',
  'Precipitation and Crystallization': 'precipitationCrystallization',
  电化学回收: 'electrochemicalRecovery',
  'Electrochemical Recovery': 'electrochemicalRecovery',
  实验报告: 'experimentalReports',
  'Experimental Reports': 'experimentalReports',
  条件优化: 'conditionOptimization',
  'Condition Optimization': 'conditionOptimization',
  表征分析: 'characterizationAnalysis',
  'Characterization Analysis': 'characterizationAnalysis',
  中试验证: 'pilotValidation',
  'Pilot Validation': 'pilotValidation',
  设计规范: 'designSpecifications',
  'Design Specifications': 'designSpecifications',
  工艺设计: 'processDesign',
  'Process Design': 'processDesign',
  设备选型: 'equipmentSelection',
  'Equipment Selection': 'equipmentSelection',
  安全规范: 'safetySpecifications',
  'Safety Specifications': 'safetySpecifications',
  标准法规: 'standardsRegulations',
  'Standards and Regulations': 'standardsRegulations',
  国家标准: 'nationalStandards',
  'National Standards': 'nationalStandards',
  行业标准: 'industryStandards',
  'Industry Standards': 'industryStandards',
  环境法规: 'environmentalRegulations',
  环保法规: 'environmentalRegulations',
  'Environmental Regulations': 'environmentalRegulations',
};

const PROJECT_DIRECTORY_KEYS_BY_NAME: Record<string, string> = {
  项目管理: 'project.detail.defaultDirectory.projectManagement',
  'Project Management': 'project.detail.defaultDirectory.projectManagement',
  项目合同文件: 'project.detail.defaultDirectory.projectContract',
  'Project Contracts': 'project.detail.defaultDirectory.projectContract',
  项目程序文件: 'project.detail.defaultDirectory.projectProcedure',
  'Project Procedures': 'project.detail.defaultDirectory.projectProcedure',
  项目组织机构与通讯录: 'project.detail.defaultDirectory.projectOrganization',
  'Organization and Contacts': 'project.detail.defaultDirectory.projectOrganization',
  WBS: 'project.detail.defaultDirectory.wbs',
  项目模板文件: 'project.detail.defaultDirectory.projectTemplate',
  'Project Templates': 'project.detail.defaultDirectory.projectTemplate',
  项目进度计划: 'project.detail.defaultDirectory.projectSchedule',
  'Project Schedule': 'project.detail.defaultDirectory.projectSchedule',
  项目月报: 'project.detail.defaultDirectory.monthlyReport',
  'Monthly Reports': 'project.detail.defaultDirectory.monthlyReport',
  会议纪要: 'project.detail.defaultDirectory.meetingMinutes',
  'Meeting Minutes': 'project.detail.defaultDirectory.meetingMinutes',
  设计资料: 'project.detail.defaultDirectory.designData',
  'Design Data': 'project.detail.defaultDirectory.designData',
  设计输入资料: 'project.detail.defaultDirectory.designInput',
  'Design Inputs': 'project.detail.defaultDirectory.designInput',
  设计基础: 'project.detail.defaultDirectory.designBasis',
  'Design Basis': 'project.detail.defaultDirectory.designBasis',
  设计成品文件: 'project.detail.defaultDirectory.designOutput',
  'Design Deliverables': 'project.detail.defaultDirectory.designOutput',
  厂商资料: 'project.detail.defaultDirectory.vendorData',
  'Vendor Data': 'project.detail.defaultDirectory.vendorData',
  专业资料: 'project.detail.defaultDirectory.disciplineData',
  'Discipline Data': 'project.detail.defaultDirectory.disciplineData',
  项目统一规定: 'project.detail.defaultDirectory.projectGeneralRules',
  'Project General Rules': 'project.detail.defaultDirectory.projectGeneralRules',
  工艺: 'project.detail.defaultDirectory.process',
  Process: 'project.detail.defaultDirectory.process',
  管道: 'project.detail.defaultDirectory.piping',
  Piping: 'project.detail.defaultDirectory.piping',
  设备: 'project.detail.defaultDirectory.equipment',
  Equipment: 'project.detail.defaultDirectory.equipment',
  仪表: 'project.detail.defaultDirectory.instrument',
  Instrumentation: 'project.detail.defaultDirectory.instrument',
  电气: 'project.detail.defaultDirectory.electrical',
  Electrical: 'project.detail.defaultDirectory.electrical',
  结构: 'project.detail.defaultDirectory.structure',
  Structure: 'project.detail.defaultDirectory.structure',
  造价: 'project.detail.defaultDirectory.cost',
  Cost: 'project.detail.defaultDirectory.cost',
  拆解: 'project.detail.defaultDirectory.dismantling',
  Dismantling: 'project.detail.defaultDirectory.dismantling',
  采购资料: 'project.detail.defaultDirectory.procurementData',
  'Procurement Data': 'project.detail.defaultDirectory.procurementData',
  主合同内容: 'project.detail.defaultDirectory.mainContract',
  'Main Contract': 'project.detail.defaultDirectory.mainContract',
  采购管理: 'project.detail.defaultDirectory.procurementManagement',
  'Procurement Management': 'project.detail.defaultDirectory.procurementManagement',
  采购合同: 'project.detail.defaultDirectory.procurementContract',
  'Procurement Contracts': 'project.detail.defaultDirectory.procurementContract',
  提交检验: 'project.detail.defaultDirectory.inspectionSubmission',
  'Inspection Submissions': 'project.detail.defaultDirectory.inspectionSubmission',
  运输: 'project.detail.defaultDirectory.transportation',
  Transportation: 'project.detail.defaultDirectory.transportation',
  现场采购: 'project.detail.defaultDirectory.siteProcurement',
  'Site Procurement': 'project.detail.defaultDirectory.siteProcurement',
  状态表: 'project.detail.defaultDirectory.statusSheet',
  'Status Sheet': 'project.detail.defaultDirectory.statusSheet',
  备件: 'project.detail.defaultDirectory.spareParts',
  'Spare Parts': 'project.detail.defaultDirectory.spareParts',
  需要采购: 'project.detail.defaultDirectory.procurementRequired',
  'Procurement Requirements': 'project.detail.defaultDirectory.procurementRequired',
  内部采购合同: 'project.detail.defaultDirectory.internalProcurementContract',
  'Internal Procurement Contracts': 'project.detail.defaultDirectory.internalProcurementContract',
};

const PROJECT_DIRECTORY_KEYS_BY_CODE: Record<string, string> = {
  A: 'project.detail.defaultDirectory.projectManagement',
  'A/A01': 'project.detail.defaultDirectory.projectContract',
  A01: 'project.detail.defaultDirectory.projectContract',
  'A/A02': 'project.detail.defaultDirectory.projectProcedure',
  A02: 'project.detail.defaultDirectory.projectProcedure',
  'A/A03': 'project.detail.defaultDirectory.projectOrganization',
  A03: 'project.detail.defaultDirectory.projectOrganization',
  'A/A04': 'project.detail.defaultDirectory.wbs',
  A04: 'project.detail.defaultDirectory.wbs',
  'A/A05': 'project.detail.defaultDirectory.projectTemplate',
  A05: 'project.detail.defaultDirectory.projectTemplate',
  'A/A06': 'project.detail.defaultDirectory.projectSchedule',
  A06: 'project.detail.defaultDirectory.projectSchedule',
  'A/A07': 'project.detail.defaultDirectory.monthlyReport',
  A07: 'project.detail.defaultDirectory.monthlyReport',
  'A/A08': 'project.detail.defaultDirectory.meetingMinutes',
  A08: 'project.detail.defaultDirectory.meetingMinutes',
  E: 'project.detail.defaultDirectory.designData',
  'E/E01': 'project.detail.defaultDirectory.designInput',
  E01: 'project.detail.defaultDirectory.designInput',
  'E/E02': 'project.detail.defaultDirectory.designBasis',
  E02: 'project.detail.defaultDirectory.designBasis',
  'E/E03': 'project.detail.defaultDirectory.designOutput',
  E03: 'project.detail.defaultDirectory.designOutput',
  'E/E04': 'project.detail.defaultDirectory.vendorData',
  E04: 'project.detail.defaultDirectory.vendorData',
  D: 'project.detail.defaultDirectory.disciplineData',
  'D/00': 'project.detail.defaultDirectory.projectGeneralRules',
  'D/01': 'project.detail.defaultDirectory.process',
  'D/02': 'project.detail.defaultDirectory.piping',
  'D/03': 'project.detail.defaultDirectory.equipment',
  'D/04': 'project.detail.defaultDirectory.instrument',
  'D/05': 'project.detail.defaultDirectory.electrical',
  'D/06': 'project.detail.defaultDirectory.structure',
  'D/07': 'project.detail.defaultDirectory.cost',
  'D/08': 'project.detail.defaultDirectory.dismantling',
  P: 'project.detail.defaultDirectory.procurementData',
  'P/01': 'project.detail.defaultDirectory.mainContract',
  'P/02': 'project.detail.defaultDirectory.procurementManagement',
  'P/03': 'project.detail.defaultDirectory.procurementContract',
  'P/04': 'project.detail.defaultDirectory.inspectionSubmission',
  'P/05': 'project.detail.defaultDirectory.transportation',
  'P/06': 'project.detail.defaultDirectory.siteProcurement',
  'P/07': 'project.detail.defaultDirectory.statusSheet',
  'P/08': 'project.detail.defaultDirectory.spareParts',
  'P/09': 'project.detail.defaultDirectory.vendorData',
  'P/10': 'project.detail.defaultDirectory.procurementRequired',
  'P/11': 'project.detail.defaultDirectory.internalProcurementContract',
};

const BUILTIN_CATEGORY_KEYS_BY_CODE: Record<string, string> = {
  'base-theory': 'theoreticalKnowledge',
  'base-theoretical-knowledge': 'theoreticalKnowledge',
  'theoretical-knowledge': 'theoreticalKnowledge',
  theory: 'theoreticalKnowledge',
  'base-process': 'processTechnology',
  'base-process-leaching': 'leachingProcess',
  'base-process-extraction': 'solventExtractionSeparation',
  'base-process-crystallization': 'precipitationCrystallization',
  'base-process-electrochemical': 'electrochemicalRecovery',
  'base-lab-report': 'experimentalReports',
  'base-lab-optimization': 'conditionOptimization',
  'base-lab-analysis': 'characterizationAnalysis',
  'base-lab-pilot': 'pilotValidation',
  'base-design-standard': 'designSpecifications',
  'base-design-process': 'processDesign',
  'base-design-equipment': 'equipmentSelection',
  'base-design-safety': 'safetySpecifications',
  'base-regulation': 'standardsRegulations',
  'base-regulation-national': 'nationalStandards',
  'base-regulation-industry': 'industryStandards',
  'base-regulation-environmental': 'environmentalRegulations',
};

type CategoryIdentity = Pick<KnowledgeCategory, 'name' | 'code'>;

function projectDirectoryTranslationKey(category: CategoryIdentity, path: CategoryIdentity[] = [category]): string | undefined {
  const code = category.code.trim();
  const rootCode = path.length > 1 ? path[0]?.code.trim() : '';
  const scopedCode = rootCode ? `${rootCode}/${code}` : code;
  return PROJECT_DIRECTORY_KEYS_BY_CODE[scopedCode] || PROJECT_DIRECTORY_KEYS_BY_CODE[code] || PROJECT_DIRECTORY_KEYS_BY_NAME[category.name.trim()];
}

function categoryTranslationKey(category: CategoryIdentity, path: CategoryIdentity[] = [category]): string | undefined {
  const builtinKey = BUILTIN_CATEGORY_KEYS_BY_CODE[category.code.trim()] || BUILTIN_CATEGORY_KEYS[category.name.trim()];
  return builtinKey ? `knowledge.category.builtin.${builtinKey}` : projectDirectoryTranslationKey(category, path);
}

/**
 * 内置分类由后端动态返回，展示时优先使用稳定编码匹配译文，避免分类名称调整后回退为原文。
 */
export function localizedCategoryName(name: string, translate: (key: string) => string): string {
  const key = BUILTIN_CATEGORY_KEYS[name.trim()];
  const localeKey = key ? `knowledge.category.builtin.${key}` : PROJECT_DIRECTORY_KEYS_BY_NAME[name.trim()];
  return localeKey ? translate(localeKey) : name;
}

export function localizedCategoryLabel(
  category: CategoryIdentity,
  translate: (key: string) => string,
  path: CategoryIdentity[] = [category],
): string {
  const key = categoryTranslationKey(category, path);
  return key ? translate(key) : category.name;
}

export function localizedCategoryPath(path: string, translate: (key: string) => string): string {
  return path
    .split(/(\s*[/>]\s*)/u)
    .map((part) => (/^[\s/>]+$/u.test(part) ? part : localizedCategoryName(part, translate)))
    .join('');
}

export function localizedCategoryTreePath(categories: KnowledgeCategory[], translate: (key: string) => string): string {
  return categories.map((category, index) => localizedCategoryLabel(category, translate, categories.slice(0, index + 1))).join(' / ');
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
  labelResolver: (name: string, category: KnowledgeCategory, path: KnowledgeCategory[]) => string = (name) => name,
  path: KnowledgeCategory[] = [],
): CategoryOption[] {
  /**
   * 构建下拉框选项，使用缩进表达层级。
   */
  return categories.flatMap((category) => {
    const currentPath = [...path, category];
    return [
      {
        label: `${'　'.repeat(level)}${labelResolver(category.name, category, currentPath)}`,
        value: category.id,
        disabled: !category.enabled,
      },
      ...buildCategoryOptions(category.children || [], level + 1, labelResolver, currentPath),
    ];
  });
}

export function collectCategoryIds(category: KnowledgeCategory | undefined): number[] {
  /**
   * 收集分类自身和全部子孙分类 ID。
   */
  if (!category) return [];
  return [category.id, ...(category.children || []).flatMap((child) => collectCategoryIds(child))];
}

export function findCategoryPath(categories: KnowledgeCategory[], categoryId: number | null | undefined): KnowledgeCategory[] {
  /**
   * 返回指定分类从根到自身的路径，用于动态分类树的面包屑式展示。
   */
  if (!categoryId) return [];
  for (const category of categories) {
    if (category.id === categoryId) return [category];
    const childPath = findCategoryPath(category.children || [], categoryId);
    if (childPath.length) return [category, ...childPath];
  }
  return [];
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
