# I18n Module

## 功能

提供轻量级中英文切换能力，不引入复杂国际化库。

## 调用关系

Zustand Store 保存当前语言，`useTranslation` 读取语言并调用 `dictionary.ts` 中的 `translate` 方法。

## 输入

- `language`: `zh-CN` 或 `en-US`
- 翻译 key：界面文本

## 输出

当前语言对应的界面文本。

## 示例

```tsx
const { t } = useTranslation();
t('首页');
```
