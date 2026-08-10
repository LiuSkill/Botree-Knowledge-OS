import fs from 'node:fs';
import path from 'node:path';
import ts from 'typescript';

const root = process.cwd();
const localesRoot = path.join(root, 'src', 'locales');
const sourceRoot = path.join(root, 'src');
const workspaceRoot = path.resolve(root, '..');
const modules = fs
  .readdirSync(path.join(localesRoot, 'zh-CN'))
  .filter((fileName) => fileName.endsWith('.ts') && fileName !== 'index.ts')
  .map((fileName) => fileName.replace(/\.ts$/u, ''))
  .sort();

function collectObject(node, prefix, result, duplicates, sourceFile) {
  for (const property of node.properties) {
    if (!ts.isPropertyAssignment(property) && !ts.isShorthandPropertyAssignment(property)) continue;
    const name = property.name && (ts.isIdentifier(property.name) || ts.isStringLiteral(property.name)) ? property.name.text : '';
    if (!name) continue;
    const key = prefix ? `${prefix}.${name}` : name;
    if (result.has(key)) duplicates.push(`${sourceFile.fileName}: ${key}`);
    if (ts.isPropertyAssignment(property) && ts.isObjectLiteralExpression(property.initializer)) {
      collectObject(property.initializer, key, result, duplicates, sourceFile);
    } else if (ts.isPropertyAssignment(property) && ts.isStringLiteralLike(property.initializer)) {
      result.set(key, property.initializer.text);
    }
  }
}

function readLocale(locale) {
  const result = new Map();
  const duplicates = [];
  for (const moduleName of modules) {
    const fileName = path.join(localesRoot, locale, `${moduleName}.ts`);
    const text = fs.readFileSync(fileName, 'utf8');
    const sourceFile = ts.createSourceFile(fileName, text, ts.ScriptTarget.Latest, true);
    const exportStatement = sourceFile.statements.find(
      (statement) => ts.isExportAssignment(statement) && ts.isAsExpression(statement.expression),
    );
    const object = exportStatement?.expression.expression;
    if (!object || !ts.isObjectLiteralExpression(object)) throw new Error(`Cannot parse locale module: ${fileName}`);
    collectObject(object, moduleName, result, duplicates, sourceFile);
  }
  return { result, duplicates };
}

function collectConstStringRecord(fileName, constNames) {
  const text = fs.readFileSync(fileName, 'utf8');
  const sourceFile = ts.createSourceFile(fileName, text, ts.ScriptTarget.Latest, true);
  const names = new Set(constNames);
  const records = new Map();

  function visit(node) {
    if (ts.isVariableStatement(node)) {
      for (const declaration of node.declarationList.declarations) {
        if (!ts.isIdentifier(declaration.name) || !names.has(declaration.name.text)) continue;
        const initializer = unwrapExpression(declaration.initializer);
        if (!initializer || !ts.isObjectLiteralExpression(initializer)) continue;
        for (const property of initializer.properties) {
          if (!ts.isPropertyAssignment(property)) continue;
          const name = property.name && (ts.isIdentifier(property.name) || ts.isStringLiteral(property.name)) ? property.name.text : '';
          const value = unwrapExpression(property.initializer);
          if (name && value && ts.isStringLiteralLike(value)) records.set(name, value.text);
        }
      }
    }
    ts.forEachChild(node, visit);
  }

  visit(sourceFile);
  return records;
}

function unwrapExpression(node) {
  if (!node) return undefined;
  if (ts.isAsExpression(node) || ts.isSatisfiesExpression(node) || ts.isParenthesizedExpression(node)) return unwrapExpression(node.expression);
  return node;
}

function collectBackendMenuIds() {
  const rbacFile = path.join(workspaceRoot, 'backend', 'app', 'core', 'rbac.py');
  if (!fs.existsSync(rbacFile)) return [];
  const text = fs.readFileSync(rbacFile, 'utf8');
  return [...new Set([...text.matchAll(/MenuNode\(\s*["']([^"']+)["']/g)].map((match) => match[1]))].sort();
}

function collectSeededBaseCategoryNames() {
  const initSqlFile = path.join(workspaceRoot, 'scripts', 'init_mysql.sql');
  if (!fs.existsSync(initSqlFile)) return [];
  const text = fs.readFileSync(initSqlFile, 'utf8');
  return [...new Set([...text.matchAll(/SELECT\s+'base',\s+NULL,\s+[^,]+,\s+'([^']+)',\s+'base-/g)].map((match) => match[1]))].sort();
}

function collectDefaultProjectDirectoryNames() {
  const templateFile = path.join(workspaceRoot, 'backend', 'app', 'core', 'project_directory_template.py');
  if (!fs.existsSync(templateFile)) return [];
  const text = fs.readFileSync(templateFile, 'utf8');
  return [...new Set([...text.matchAll(/\(\s*["'][^"']+["']\s*,\s*["']([^"']+)["']/g)].map((match) => match[1]))].sort();
}

function walk(directory) {
  return fs.readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const target = path.join(directory, entry.name);
    if (entry.isDirectory()) return walk(target);
    return /\.(vue|ts)$/.test(entry.name) ? [target] : [];
  });
}

const zh = readLocale('zh-CN');
const en = readLocale('en-US');
const errors = [...zh.duplicates, ...en.duplicates];
for (const key of zh.result.keys()) if (!en.result.has(key)) errors.push(`Missing en-US key: ${key}`);
for (const key of en.result.keys()) if (!zh.result.has(key)) errors.push(`Missing zh-CN key: ${key}`);
for (const [key, value] of zh.result) if (!value.trim()) errors.push(`Empty zh-CN translation: ${key}`);
for (const [key, value] of en.result) if (!value.trim()) errors.push(`Empty en-US translation: ${key}`);

const menuKeyById = collectConstStringRecord(path.join(sourceRoot, 'utils', 'localizedNavigation.ts'), ['MENU_KEY_BY_ID']);
for (const menuId of collectBackendMenuIds()) {
  if (!menuKeyById.has(menuId)) errors.push(`Missing menu translation mapping for backend menu id: ${menuId}`);
}
for (const [menuId, key] of menuKeyById) {
  if (!zh.result.has(key)) errors.push(`Menu mapping references missing zh-CN key: ${menuId} -> ${key}`);
  if (!en.result.has(key)) errors.push(`Menu mapping references missing en-US key: ${menuId} -> ${key}`);
}

const categoryUtilFile = path.join(sourceRoot, 'utils', 'categories.ts');
const categoryKeyByName = collectConstStringRecord(categoryUtilFile, [
  'BUILTIN_CATEGORY_KEYS',
  'BUILTIN_CATEGORY_KEYS_BY_NAME',
]);
const categoryKeyByCode = collectConstStringRecord(categoryUtilFile, ['BUILTIN_CATEGORY_KEYS_BY_CODE']);
const projectDirectoryKeyByName = collectConstStringRecord(categoryUtilFile, ['PROJECT_DIRECTORY_KEYS_BY_NAME']);
const projectDirectoryKeyByCode = collectConstStringRecord(categoryUtilFile, ['PROJECT_DIRECTORY_KEYS_BY_CODE']);
const requiredCategoryNames = [...new Set([...collectSeededBaseCategoryNames(), '理论知识'])].sort();
for (const categoryName of requiredCategoryNames) {
  if (!categoryKeyByName.has(categoryName)) errors.push(`Missing builtin category translation mapping for name: ${categoryName}`);
}
for (const [categoryName, builtinKey] of [...categoryKeyByName, ...categoryKeyByCode]) {
  const key = `knowledge.category.builtin.${builtinKey}`;
  if (!zh.result.has(key)) errors.push(`Category mapping references missing zh-CN key: ${categoryName} -> ${key}`);
  if (!en.result.has(key)) errors.push(`Category mapping references missing en-US key: ${categoryName} -> ${key}`);
}
for (const directoryName of collectDefaultProjectDirectoryNames()) {
  if (!projectDirectoryKeyByName.has(directoryName)) errors.push(`Missing project directory translation mapping for name: ${directoryName}`);
}
for (const [directoryName, key] of [...projectDirectoryKeyByName, ...projectDirectoryKeyByCode]) {
  if (!zh.result.has(key)) errors.push(`Project directory mapping references missing zh-CN key: ${directoryName} -> ${key}`);
  if (!en.result.has(key)) errors.push(`Project directory mapping references missing en-US key: ${directoryName} -> ${key}`);
}

const sourceFiles = walk(sourceRoot).filter((file) => !file.includes(`${path.sep}locales${path.sep}`));
const usedKeys = new Set();
const hardcoded = [];
for (const fileName of sourceFiles) {
  const relative = path.relative(root, fileName).replaceAll('\\', '/');
  const text = fs.readFileSync(fileName, 'utf8');
  for (const match of text.matchAll(/\bt\(\s*['"]([a-z][\w.-]+)['"]/g)) usedKeys.add(match[1]);
  if (!/(mocks|types|api)\//.test(relative)) {
    const sourceFile = ts.createSourceFile(fileName, text, ts.ScriptTarget.Latest, true, fileName.endsWith('.vue') ? ts.ScriptKind.TSX : ts.ScriptKind.TS);
    const commentRanges = [...(ts.getLeadingCommentRanges(text, 0) || [])];
    const lines = text.split(/\r?\n/);
    lines.forEach((line, index) => {
      if (/<!--[\s\S]*-->|^\s*(\/\/|\*|\/\*)/.test(line)) return;
      if (/[\u3400-\u9fff]/u.test(line) && /(['"]|>)[^<]*[\u3400-\u9fff]/u.test(line)) hardcoded.push(`${relative}:${index + 1}`);
    });
    void sourceFile; void commentRanges;
  }
}

for (const key of usedKeys) if (!zh.result.has(key)) errors.push(`Used key is missing from locale files: ${key}`);
const unused = [...zh.result.keys()].filter((key) => !usedKeys.has(key));

if (errors.length) {
  console.error(errors.join('\n'));
  process.exitCode = 1;
} else {
  console.log(`Locale key parity passed (${zh.result.size} keys).`);
}
console.log(`Potential unused keys: ${unused.length}`);
console.log(`Potential hardcoded Chinese locations: ${hardcoded.length}`);
if (hardcoded.length) console.log(hardcoded.slice(0, 120).join('\n'));
