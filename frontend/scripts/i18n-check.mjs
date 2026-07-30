import fs from 'node:fs';
import path from 'node:path';
import ts from 'typescript';

const root = process.cwd();
const localesRoot = path.join(root, 'src', 'locales');
const sourceRoot = path.join(root, 'src');
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
