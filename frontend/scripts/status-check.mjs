import fs from 'node:fs';
import path from 'node:path';
import ts from 'typescript';

const root = process.cwd();
const sourceRoot = path.join(root, 'src');
const workspaceRoot = path.resolve(root, '..');

function readFile(relativePath) {
  return fs.readFileSync(path.join(workspaceRoot, relativePath), 'utf8');
}

function collectPythonStringConstants(relativePath, names) {
  const text = readFile(relativePath);
  const constants = new Map();
  for (const name of names) {
    const match = text.match(new RegExp(`^${name}\\s*=\\s*["']([^"']+)["']`, 'mu'));
    if (match) constants.set(name, match[1]);
  }
  return constants;
}

function unwrapExpression(node) {
  if (!node) return undefined;
  if (ts.isAsExpression(node) || ts.isSatisfiesExpression(node) || ts.isParenthesizedExpression(node)) return unwrapExpression(node.expression);
  return node;
}

function collectTsObjectValues(fileName, constName) {
  const text = fs.readFileSync(fileName, 'utf8');
  const sourceFile = ts.createSourceFile(fileName, text, ts.ScriptTarget.Latest, true);
  const stringConstants = collectTsStringConstants(sourceFile);
  const result = [];

  function visit(node) {
    if (ts.isVariableStatement(node)) {
      for (const declaration of node.declarationList.declarations) {
        if (!ts.isIdentifier(declaration.name) || declaration.name.text !== constName) continue;
        const initializer = unwrapExpression(declaration.initializer);
        if (!initializer || !ts.isObjectLiteralExpression(initializer)) continue;
        for (const property of initializer.properties) {
          if (!ts.isPropertyAssignment(property)) continue;
          const value = unwrapExpression(property.initializer);
          if (value && ts.isStringLiteralLike(value)) result.push(value.text);
          if (value && ts.isIdentifier(value) && stringConstants.has(value.text)) result.push(stringConstants.get(value.text));
        }
      }
    }
    ts.forEachChild(node, visit);
  }

  visit(sourceFile);
  return result;
}

function collectTsStringConstants(sourceFile) {
  const result = new Map();

  function visit(node) {
    if (ts.isVariableStatement(node)) {
      for (const declaration of node.declarationList.declarations) {
        if (!ts.isIdentifier(declaration.name)) continue;
        const initializer = unwrapExpression(declaration.initializer);
        if (initializer && ts.isStringLiteralLike(initializer)) result.set(declaration.name.text, initializer.text);
      }
    }
    ts.forEachChild(node, visit);
  }

  visit(sourceFile);
  return result;
}

function collectTsArrayValues(fileName, constName) {
  const text = fs.readFileSync(fileName, 'utf8');
  const sourceFile = ts.createSourceFile(fileName, text, ts.ScriptTarget.Latest, true);
  const stringConstants = collectTsStringConstants(sourceFile);
  const result = [];

  function visit(node) {
    if (ts.isVariableStatement(node)) {
      for (const declaration of node.declarationList.declarations) {
        if (!ts.isIdentifier(declaration.name) || declaration.name.text !== constName) continue;
        const initializer = unwrapExpression(declaration.initializer);
        if (!initializer || !ts.isArrayLiteralExpression(initializer)) continue;
        for (const element of initializer.elements) {
          const value = unwrapExpression(element);
          if (value && ts.isStringLiteralLike(value)) result.push(value.text);
          if (value && ts.isIdentifier(value) && stringConstants.has(value.text)) result.push(stringConstants.get(value.text));
        }
      }
    }
    ts.forEachChild(node, visit);
  }

  visit(sourceFile);
  return result;
}

function collectProjectDocumentStatusValues() {
  const constantsFile = path.join(sourceRoot, 'utils', 'constants.ts');
  const values = collectTsArrayValues(constantsFile, 'PROJECT_DOCUMENT_STATUS_VALUES');
  if (values.length) return values;

  const pageFile = path.join(sourceRoot, 'views', 'project', 'ProjectDocumentManagePage.vue');
  const text = fs.readFileSync(pageFile, 'utf8');
  const match = text.match(/const\s+documentStatusOptions\s*=\s*computed\(\(\)\s*=>\s*\[([\s\S]*?)\]\);/u);
  return match ? [...match[1].matchAll(/value:\s*['"]([^'"]+)['"]/gu)].map((item) => item[1]) : [];
}

function assertSameSet(name, actual, expected, errors) {
  const actualSet = new Set(actual);
  const expectedSet = new Set(expected);
  for (const value of expectedSet) {
    if (!actualSet.has(value)) errors.push(`${name} missing database status: ${value}`);
  }
  for (const value of actualSet) {
    if (!expectedSet.has(value)) errors.push(`${name} contains non-database status: ${value}`);
  }
}

const serviceConstants = collectPythonStringConstants('backend/app/services/document_service.py', [
  'PROJECT_DOCUMENT_STATUS_PENDING',
  'PROJECT_DOCUMENT_STATUS_REVIEWING',
  'PROJECT_DOCUMENT_STATUS_REJECTED',
  'PROJECT_DOCUMENT_STATUS_PUBLISHED',
  'PARSE_STATUS_PARSING',
  'PARSE_STATUS_SUCCESS',
  'PARSE_STATUS_FAILED',
  'INDEX_STATUS_NOT_INDEXED',
  'INDEX_STATUS_INDEXED',
  'INDEX_STATUS_FAILED',
  'REVIEW_STATUS_REVIEWING',
  'REVIEW_STATUS_APPROVED',
  'REVIEW_STATUS_REJECTED',
]);

const constantsFile = path.join(sourceRoot, 'utils', 'constants.ts');
const errors = [];

assertSameSet(
  'Project document status filter options',
  collectProjectDocumentStatusValues(),
  [
    serviceConstants.get('PROJECT_DOCUMENT_STATUS_PENDING'),
    serviceConstants.get('PROJECT_DOCUMENT_STATUS_REVIEWING'),
    serviceConstants.get('PROJECT_DOCUMENT_STATUS_REJECTED'),
    serviceConstants.get('PROJECT_DOCUMENT_STATUS_PUBLISHED'),
  ].filter(Boolean),
  errors,
);

assertSameSet(
  'Parse status filter options',
  collectTsArrayValues(constantsFile, 'PARSE_STATUS_OPTION_VALUES'),
  [
    serviceConstants.get('PARSE_STATUS_PARSING'),
    serviceConstants.get('PARSE_STATUS_FAILED'),
    serviceConstants.get('PARSE_STATUS_SUCCESS'),
  ].filter(Boolean),
  errors,
);

assertSameSet(
  'Index status filter options',
  collectTsArrayValues(constantsFile, 'INDEX_STATUS_OPTION_VALUES'),
  [
    serviceConstants.get('INDEX_STATUS_NOT_INDEXED'),
    serviceConstants.get('INDEX_STATUS_FAILED'),
    serviceConstants.get('INDEX_STATUS_INDEXED'),
  ].filter(Boolean),
  errors,
);

assertSameSet(
  'Review task status filter options',
  collectTsObjectValues(constantsFile, 'REVIEW_TASK_STATUS'),
  [
    serviceConstants.get('REVIEW_STATUS_REVIEWING'),
    serviceConstants.get('REVIEW_STATUS_REJECTED'),
    serviceConstants.get('REVIEW_STATUS_APPROVED'),
  ].filter(Boolean),
  errors,
);

if (errors.length) {
  console.error(errors.join('\n'));
  process.exitCode = 1;
} else {
  console.log('Knowledge document status filter options match backend database status constants.');
}
