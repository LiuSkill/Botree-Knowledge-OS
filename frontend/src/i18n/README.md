# Legacy I18n Module

## 功能

历史说明目录。当前系统已迁移到 `src/locales`，使用 `vue-i18n` 统一管理中英文语言包。

## 调用关系

`src/locales/index.ts` 创建 i18n 实例，`src/stores/locale.ts` 负责语言状态、LocalStorage 持久化和 HTML `lang` 同步。

## 输入

- `language`: `zh-CN` 或 `en-US`
- 翻译 key：语义化模块 key

## 输出

当前语言对应的界面文本。

## 示例

```ts
const { t } = useI18n();
t('common.action.save');
```
