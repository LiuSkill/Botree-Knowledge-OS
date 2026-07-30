import type { ComposerTranslation } from 'vue-i18n';

const MENU_KEY_BY_ID: Record<string, string> = {
  dashboard: 'menu.dashboard', knowledge: 'menu.knowledge', project: 'menu.project', authorization: 'menu.authorization', review: 'menu.review',
  process_config: 'menu.processConfig', 'process_config:material': 'menu.material', 'process_config:product': 'menu.product',
  'process_config:consumable': 'menu.consumable', 'process_config:public_service': 'menu.publicService', 'process_config:labor_cost': 'menu.laborCost',
  'process_config:equipment_asset': 'menu.equipmentAsset', 'process_config:infrastructure_asset': 'menu.infrastructureAsset',
  'process_config:node': 'menu.processNode', 'process_config:route': 'menu.processRoute', 'process_config:calculator': 'menu.calculator',
  ai: 'menu.ai', 'ai:project-chat': 'menu.projectChat', 'ai:base-chat': 'menu.baseChat', system: 'menu.system',
  'system:user': 'menu.user', 'system:department:view': 'menu.department', 'system:permission': 'menu.permission',
  'system:model-config': 'menu.modelConfig', 'system:operation-log': 'menu.operationLog', 'system:qa-audit': 'menu.qaAudit',
  'system:sensitive-content': 'menu.sensitiveContent',
};

export function menuLabel(menuId: string, fallback: string, t: ComposerTranslation): string {
  const key = MENU_KEY_BY_ID[menuId];
  return key ? t(key) : fallback;
}

export function menuTitleKey(menuId: string): string | undefined {
  return MENU_KEY_BY_ID[menuId];
}
