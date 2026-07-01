<script setup lang="ts">
import katex from 'katex';
import 'katex/contrib/mhchem';
import 'katex/dist/katex.min.css';
import MarkdownIt from 'markdown-it';
import { computed } from 'vue';

const props = defineProps<{
  content: string;
  imageSourceResolver?: (src: string) => string | null | undefined;
}>();

interface MathPlaceholder {
  token: string;
  html: string;
}

const SAFE_MARKDOWN_TAGS = new Set([
  'a',
  'blockquote',
  'br',
  'caption',
  'code',
  'col',
  'colgroup',
  'del',
  'div',
  'em',
  'h1',
  'h2',
  'h3',
  'h4',
  'h5',
  'h6',
  'hr',
  'img',
  'li',
  'ol',
  'p',
  'pre',
  's',
  'span',
  'strong',
  'sub',
  'sup',
  'table',
  'tbody',
  'td',
  'tfoot',
  'th',
  'thead',
  'tr',
  'ul',
]);
const SAFE_TABLE_ATTRS = new Set(['align', 'colspan', 'rowspan']);
const SAFE_COL_ATTRS = new Set(['span', 'width']);
const SAFE_STYLE_PROPERTIES = new Set(['text-align', 'vertical-align', 'width', 'height']);
const CHEMICAL_SCRIPT_PATTERN = /([A-Za-z\)\]])([_^])\{?([0-9+\-]+)\}?/g;
const CHEMICAL_FORMULA_CANDIDATE_PATTERN =
  /(^|[^A-Za-z0-9_\\])([A-Z][A-Za-z0-9()[\]{}.+\-^·₀₁₂₃₄₅₆₇₈₉₊₋⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻]{1,48})(?=$|[^A-Za-z0-9_])/gu;
const HTML_IMAGE_SRC_PATTERN = /<img\b[^>]*\bsrc\s*=\s*(?:"([^"]+)"|'([^']+)'|([^>\s]+))/gi;
const PIPE_TABLE_DELIMITER_CELL = String.raw`\s*:?-{3,}:?\s*`;
const MERGED_PIPE_TABLE_SEPARATOR_PATTERN = new RegExp(
  String.raw`\|\s*(\|${PIPE_TABLE_DELIMITER_CELL}(?:\|${PIPE_TABLE_DELIMITER_CELL})+\|?\s*)$`,
  'u',
);
const ELEMENT_SYMBOLS = new Set(
  (
    'H He Li Be B C N O F Ne Na Mg Al Si P S Cl Ar K Ca Sc Ti V Cr Mn Fe Co Ni Cu Zn Ga Ge As Se Br Kr ' +
    'Rb Sr Y Zr Nb Mo Tc Ru Rh Pd Ag Cd In Sn Sb Te I Xe Cs Ba La Ce Pr Nd Pm Sm Eu Gd Tb Dy Ho Er Tm Yb Lu ' +
    'Hf Ta W Re Os Ir Pt Au Hg Tl Pb Bi Po At Rn Fr Ra Ac Th Pa U Np Pu Am Cm Bk Cf Es Fm Md No Lr Rf Db Sg ' +
    'Bh Hs Mt Ds Rg Cn Nh Fl Mc Lv Ts Og'
  ).split(' '),
);
const COMMON_NO_DIGIT_FORMULAS = new Set(['CO', 'HCl', 'HBr', 'HF', 'HI', 'KOH', 'NaCl', 'NaOH', 'OH']);
const SUBSCRIPT_NORMALIZATION_MAP: Record<string, string> = {
  '₀': '0',
  '₁': '1',
  '₂': '2',
  '₃': '3',
  '₄': '4',
  '₅': '5',
  '₆': '6',
  '₇': '7',
  '₈': '8',
  '₉': '9',
  '₊': '+',
  '₋': '-',
};
const SUPERSCRIPT_NORMALIZATION_MAP: Record<string, string> = {
  '⁰': '0',
  '¹': '1',
  '²': '2',
  '³': '3',
  '⁴': '4',
  '⁵': '5',
  '⁶': '6',
  '⁷': '7',
  '⁸': '8',
  '⁹': '9',
  '⁺': '+',
  '⁻': '-',
};

const markdownRenderer = new MarkdownIt({
  html: true,
  linkify: true,
  breaks: true,
});

markdownRenderer.renderer.rules.image = (tokens, idx) => {
  const token = tokens[idx];
  const rawSrc = token.attrGet('src') || '';
  const alt = token.content || token.attrGet('alt') || '';
  const title = token.attrGet('title') || '';
  const url = normalizeImageUrl(rawSrc);
  if (!url) {
    return escapeHtml(alt || basenameFromPath(rawSrc));
  }
  return [
    '<img class="chat-markdown-image"',
    ` src="${escapeHtml(url)}"`,
    ` alt="${escapeHtml(alt)}"`,
    title ? ` title="${escapeHtml(title)}"` : '',
    ' loading="lazy" decoding="async" />',
  ].join('');
};

const renderedHtml = computed(() => renderRichMarkdown(props.content));

function escapeHtml(value: string): string {
  return value
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

function basenameFromPath(value: string): string {
  const cleanValue = value.split(/[?#]/)[0].replace(/\\/g, '/');
  return cleanValue.split('/').filter(Boolean).pop() || value;
}

function normalizeImageUrl(src: string): string {
  const resolvedUrl = props.imageSourceResolver?.(src)?.trim() || '';
  if (resolvedUrl && isSafeImageUrl(resolvedUrl)) return resolvedUrl;

  const value = src.trim();
  if (isSafeImageUrl(value)) return value;
  return '';
}

function isSafeImageUrl(value: string): boolean {
  if (/^(https?:|blob:|\/)/i.test(value)) return true;
  if (/^data:image\/(?:png|jpe?g|gif|webp|svg\+xml);base64,/i.test(value)) return true;
  return false;
}

function decodeAllowedHtmlEntities(value: string): string {
  return value
    .replace(/&(amp;)?quot;/gi, '"')
    .replace(/&(amp;)?#39;/gi, "'")
    .replace(/&(amp;)?amp;/gi, '&');
}

function restoreAllowedEncodedHtml(markdown: string): string {
  // 历史解析结果可能把表格和图片标签实体化，这里只恢复展示所需白名单标签。
  return markdown.replace(
    /&(amp;)?lt;(\/?)(table|thead|tbody|tfoot|tr|td|th|br|colgroup|col|caption|img)\b([\s\S]*?)&(amp;)?gt;/gi,
    (_match, _ltAmp: string, slash: string, tag: string, attrs: string) =>
      `<${slash}${tag.toLowerCase()}${decodeAllowedHtmlEntities(attrs)}>`,
  );
}

function buildOrphanTableRow(line: string): string {
  const matches = Array.from(line.matchAll(/<(td|th)\b([^>]*)>/gi));
  if (!matches.length) return line;
  const cells = matches.map((match, index) => {
    const tag = match[1].toLowerCase();
    const attrs = match[2] || '';
    const contentStart = (match.index || 0) + match[0].length;
    const contentEnd = index + 1 < matches.length ? matches[index + 1].index || line.length : line.length;
    const content = line.slice(contentStart, contentEnd).replace(/<\/(?:td|th)>\s*$/i, '').trim();
    return `<${tag}${attrs}>${content}</${tag}>`;
  });
  return `<tr>${cells.join('')}</tr>`;
}

function normalizeOrphanTableRows(markdown: string): string {
  const output: string[] = [];
  const tableRows: string[] = [];
  let inCodeBlock = false;
  let rawTableDepth = 0;

  const flushTableRows = () => {
    if (!tableRows.length) return;
    output.push(`<table><tbody>${tableRows.join('\n')}</tbody></table>`);
    tableRows.length = 0;
  };

  for (const line of markdown.replace(/\r\n/g, '\n').split('\n')) {
    const trimmedLine = line.trim();
    if (/^(```|~~~)/.test(trimmedLine)) {
      flushTableRows();
      output.push(line);
      inCodeBlock = !inCodeBlock;
      continue;
    }
    if (!inCodeBlock && rawTableDepth === 0 && /^<(td|th)\b/i.test(trimmedLine) && !/^<tr\b/i.test(trimmedLine)) {
      tableRows.push(buildOrphanTableRow(trimmedLine));
      continue;
    }
    flushTableRows();
    output.push(line);
    if (!inCodeBlock) {
      const openingTables = (trimmedLine.match(/<table\b/gi) || []).length;
      const closingTables = (trimmedLine.match(/<\/table>/gi) || []).length;
      rawTableDepth = Math.max(0, rawTableDepth + openingTables - closingTables);
    }
  }

  flushTableRows();
  return output.join('\n');
}

function splitMergedPipeTableSeparator(line: string): string {
  return line.replace(MERGED_PIPE_TABLE_SEPARATOR_PATTERN, '|\n$1');
}

function normalizeMergedPipeTableSeparators(markdown: string): string {
  const output: string[] = [];
  let inCodeBlock = false;
  let codeFence = '';

  for (const line of markdown.replace(/\r\n/g, '\n').split('\n')) {
    const trimmedLine = line.trim();
    const fenceMatch = trimmedLine.match(/^(```|~~~)/);
    if (fenceMatch) {
      output.push(line);
      if (!inCodeBlock) {
        inCodeBlock = true;
        codeFence = fenceMatch[1];
      } else if (trimmedLine.startsWith(codeFence)) {
        inCodeBlock = false;
        codeFence = '';
      }
      continue;
    }

    // 流式回答偶发把表头与分隔行黏连，补回换行后才能按 Markdown 表格渲染。
    output.push(inCodeBlock ? line : splitMergedPipeTableSeparator(line));
  }

  return output.join('\n');
}

function isPipeTableRow(line: string): boolean {
  const trimmedLine = line.trim();
  const pipeCount = (trimmedLine.match(/\|/g) || []).length;
  return trimmedLine.startsWith('|') && trimmedLine.endsWith('|') && pipeCount >= 3;
}

function isPipeTableDelimiterRow(line: string): boolean {
  return new RegExp(String.raw`^\s*\|(?:${PIPE_TABLE_DELIMITER_CELL}\|)+\s*$`, 'u').test(line);
}

function buildPipeTableDelimiter(headerRow: string): string {
  const columnCount = Math.max(2, headerRow.trim().split('|').length - 2);
  return `| ${Array.from({ length: columnCount }, () => '---').join(' | ')} |`;
}

function normalizePipeTableBlocks(markdown: string): string {
  const output: string[] = [];
  const tableRows: string[] = [];
  let inCodeBlock = false;
  let codeFence = '';

  const flushTableRows = () => {
    if (!tableRows.length) return;
    if (tableRows.length === 1) {
      output.push(tableRows[0]);
      tableRows.length = 0;
      return;
    }

    output.push(tableRows[0]);
    if (!isPipeTableDelimiterRow(tableRows[1])) {
      // 检索片段常只有多行管道文本，补充分隔行后才能被 markdown-it 识别为表格。
      output.push(buildPipeTableDelimiter(tableRows[0]));
    }
    output.push(...tableRows.slice(1));
    tableRows.length = 0;
  };

  for (const line of markdown.replace(/\r\n/g, '\n').split('\n')) {
    const trimmedLine = line.trim();
    const fenceMatch = trimmedLine.match(/^(```|~~~)/);
    if (fenceMatch) {
      flushTableRows();
      output.push(line);
      if (!inCodeBlock) {
        inCodeBlock = true;
        codeFence = fenceMatch[1];
      } else if (trimmedLine.startsWith(codeFence)) {
        inCodeBlock = false;
        codeFence = '';
      }
      continue;
    }

    if (!inCodeBlock && isPipeTableRow(line)) {
      tableRows.push(line);
      continue;
    }

    flushTableRows();
    output.push(line);
  }

  flushTableRows();
  return output.join('\n');
}

function preprocessMarkdown(markdown: string): string {
  return normalizePipeTableBlocks(
    normalizeOrphanTableRows(normalizeMergedPipeTableSeparators(restoreAllowedEncodedHtml(markdown))),
  );
}

function isEscaped(value: string, index: number): boolean {
  let slashCount = 0;
  for (let cursor = index - 1; cursor >= 0 && value[cursor] === '\\'; cursor -= 1) {
    slashCount += 1;
  }
  return slashCount % 2 === 1;
}

function normalizeUnicodeChemicalScripts(value: string): string {
  let output = '';
  let inSuperscript = false;
  for (const char of value) {
    if (SUBSCRIPT_NORMALIZATION_MAP[char]) {
      output += SUBSCRIPT_NORMALIZATION_MAP[char];
      inSuperscript = false;
      continue;
    }
    if (SUPERSCRIPT_NORMALIZATION_MAP[char]) {
      if (!inSuperscript) {
        output += '^';
        inSuperscript = true;
      }
      output += SUPERSCRIPT_NORMALIZATION_MAP[char];
      continue;
    }
    output += char;
    inSuperscript = false;
  }
  return output;
}

function normalizeChemicalFormulaSource(value: string): string {
  return normalizeUnicodeChemicalScripts(value)
    .replace(/[−–—]/g, '-')
    .replace(/＋/g, '+')
    .replace(/\\(?:mathrm|mathbf|text|operatorname)\s*\{([^{}]*)\}\}?/g, '$1')
    .replace(/\\(?:rm|bf|it)\s+/g, '')
    .replace(/\\cdot\b/g, '·')
    .replace(/\\[,;:!]\s*/g, '')
    .replace(/_\s*\{\s*([^{}]+)\s*\}/g, '$1')
    .replace(/_\s*([0-9+\-]+)/g, '$1')
    .replace(/\^\s*\{\s*([^{}]+)\s*\}/g, '^$1')
    .replace(/\^\s*([0-9+\-]+)/g, '^$1')
    .replace(/[{}]/g, '')
    .replace(/\s+/g, '');
}

function trimFormulaPunctuation(value: string): { core: string; suffix: string } {
  let core = value;
  let suffix = '';
  while (core && /[.,;:，。；：]/u.test(core[core.length - 1])) {
    suffix = `${core[core.length - 1]}${suffix}`;
    core = core.slice(0, -1);
  }
  return { core, suffix };
}

function scanChemicalFormula(value: string): {
  elementCount: number;
  hasCharge: boolean;
  hasGroup: boolean;
  hasLowercase: boolean;
  hasNumber: boolean;
  valid: boolean;
} {
  let cursor = 0;
  let elementCount = 0;
  let hasCharge = false;
  let hasGroup = false;
  let hasLowercase = false;
  let hasNumber = false;

  while (cursor < value.length) {
    const char = value[cursor];
    if (/[A-Z]/.test(char)) {
      const twoLetterSymbol = value.slice(cursor, cursor + 2);
      const oneLetterSymbol = value[cursor];
      if (ELEMENT_SYMBOLS.has(twoLetterSymbol)) {
        elementCount += 1;
        hasLowercase = true;
        cursor += 2;
        continue;
      }
      if (ELEMENT_SYMBOLS.has(oneLetterSymbol)) {
        elementCount += 1;
        cursor += 1;
        continue;
      }
      return { elementCount, hasCharge, hasGroup, hasLowercase, hasNumber, valid: false };
    }
    if (/[a-z]/.test(char)) {
      return { elementCount, hasCharge, hasGroup, hasLowercase, hasNumber, valid: false };
    }
    if (/\d/.test(char)) {
      hasNumber = true;
      cursor += 1;
      continue;
    }
    if ('()[]'.includes(char)) {
      hasGroup = true;
      cursor += 1;
      continue;
    }
    if (char === '^') {
      hasCharge = true;
      cursor += 1;
      continue;
    }
    if (char === '+' || char === '-') {
      hasCharge = true;
      cursor += 1;
      continue;
    }
    if (char === '·' || char === '.') {
      cursor += 1;
      continue;
    }
    return { elementCount, hasCharge, hasGroup, hasLowercase, hasNumber, valid: false };
  }

  return { elementCount, hasCharge, hasGroup, hasLowercase, hasNumber, valid: true };
}

function isLikelyChemicalFormula(value: string): boolean {
  const normalized = normalizeChemicalFormulaSource(value);
  if (normalized.length < 2 || normalized.length > 80) return false;
  if (!/^[A-Za-z0-9()[\]^+\-.·]+$/.test(normalized)) return false;
  const scanResult = scanChemicalFormula(normalized);
  if (!scanResult.valid || scanResult.elementCount === 0) return false;
  if (scanResult.hasNumber || scanResult.hasGroup || scanResult.hasCharge) return true;
  return scanResult.hasLowercase || COMMON_NO_DIGIT_FORMULAS.has(normalized);
}

function normalizeMathSource(source: string): string {
  const expression = source.trim();
  if (/^\\(?:ce|pu)\s*\{/.test(expression)) return expression;
  const chemicalSource = normalizeChemicalFormulaSource(expression);
  if (isLikelyChemicalFormula(chemicalSource)) {
    return `\\ce{${chemicalSource}}`;
  }
  return expression;
}

function renderMathToHtml(source: string, displayMode: boolean): string {
  const expression = normalizeMathSource(source);
  if (!expression) return '';
  try {
    return katex.renderToString(expression, {
      displayMode,
      throwOnError: false,
      strict: 'ignore',
      trust: false,
      output: 'htmlAndMathml',
    });
  } catch {
    return `<code class="chat-math-error">${escapeHtml(expression)}</code>`;
  }
}

function createMathToken(placeholders: MathPlaceholder[], source: string, displayMode: boolean, prefix: string): string {
  const token = `${prefix}${placeholders.length}END`;
  const mathHtml = renderMathToHtml(source, displayMode);
  placeholders.push({
    token,
    html: displayMode ? `<div class="chat-math-block">${mathHtml}</div>` : `<span class="chat-math-inline">${mathHtml}</span>`,
  });
  return token;
}

function replaceInlineMath(line: string, placeholders: MathPlaceholder[], prefix: string): string {
  let output = '';
  let cursor = 0;

  while (cursor < line.length) {
    const latexStart = line.slice(cursor, cursor + 2);
    if ((latexStart === '\\(' || latexStart === '\\[') && !isEscaped(line, cursor)) {
      const closing = latexStart === '\\(' ? '\\)' : '\\]';
      const end = line.indexOf(closing, cursor + 2);
      if (end > cursor) {
        const source = line.slice(cursor + 2, end);
        output += createMathToken(placeholders, source, latexStart === '\\[', prefix);
        cursor = end + 2;
        continue;
      }
    }

    if (line[cursor] === '$' && !isEscaped(line, cursor) && line[cursor + 1] !== '$') {
      let end = cursor + 1;
      while (end < line.length) {
        if (line[end] === '$' && !isEscaped(line, end)) break;
        end += 1;
      }
      if (end < line.length) {
        const source = line.slice(cursor + 1, end);
        if (source.trim()) {
          output += createMathToken(placeholders, source, false, prefix);
          cursor = end + 1;
          continue;
        }
      }
    }

    output += line[cursor];
    cursor += 1;
  }

  return output;
}

function replaceStandaloneChemistry(line: string, placeholders: MathPlaceholder[], prefix: string): string {
  return line.replace(/\\ce\s*\{([^{}]*(?:\{[^{}]*\}[^{}]*)*)\}/g, (match) =>
    createMathToken(placeholders, match, false, prefix),
  );
}

function replacePlainChemistry(line: string, placeholders: MathPlaceholder[], prefix: string): string {
  return line.replace(CHEMICAL_FORMULA_CANDIDATE_PATTERN, (match, boundary: string, rawFormula: string) => {
    const { core, suffix } = trimFormulaPunctuation(rawFormula);
    if (!core || !isLikelyChemicalFormula(core)) return match;
    const chemicalSource = normalizeChemicalFormulaSource(core);
    return `${boundary}${createMathToken(placeholders, `\\ce{${chemicalSource}}`, false, prefix)}${suffix}`;
  });
}

function protectMath(markdown: string): { markdown: string; placeholders: MathPlaceholder[] } {
  const placeholders: MathPlaceholder[] = [];
  const tokenPrefix = `CHATMATH${Math.random().toString(36).slice(2)}TOKEN`;
  const lines = markdown.replace(/\r\n/g, '\n').split('\n');
  const output: string[] = [];
  let inCodeBlock = false;
  let blockMath: string[] = [];

  for (const line of lines) {
    const trimmedLine = line.trim();
    if (/^(```|~~~)/.test(trimmedLine)) {
      if (blockMath.length) {
        output.push(...blockMath);
        blockMath = [];
      }
      output.push(line);
      inCodeBlock = !inCodeBlock;
      continue;
    }
    if (inCodeBlock) {
      output.push(line);
      continue;
    }

    if (blockMath.length) {
      if (trimmedLine.endsWith('$$')) {
        blockMath.push(line.slice(0, line.lastIndexOf('$$')));
        output.push(createMathToken(placeholders, blockMath.join('\n'), true, tokenPrefix));
        blockMath = [];
      } else {
        blockMath.push(line);
      }
      continue;
    }

    if (trimmedLine.startsWith('$$')) {
      const rest = line.slice(line.indexOf('$$') + 2);
      const closingIndex = rest.lastIndexOf('$$');
      if (closingIndex >= 0) {
        output.push(createMathToken(placeholders, rest.slice(0, closingIndex), true, tokenPrefix));
      } else {
        blockMath.push(rest);
      }
      continue;
    }

    const protectedChemistry = replaceStandaloneChemistry(line, placeholders, tokenPrefix);
    const protectedMath = replaceInlineMath(protectedChemistry, placeholders, tokenPrefix);
    output.push(replacePlainChemistry(protectedMath, placeholders, tokenPrefix));
  }

  if (blockMath.length) {
    output.push(`$$${blockMath.join('\n')}`);
  }

  return { markdown: output.join('\n'), placeholders };
}

function sanitizeStyle(styleValue: string): string {
  const safeDeclarations = styleValue
    .split(';')
    .map((item) => item.trim())
    .filter(Boolean)
    .filter((item) => {
      const [property, value] = item.split(':').map((part) => part?.trim() || '');
      return SAFE_STYLE_PROPERTIES.has(property.toLowerCase()) && !/url\s*\(|expression\s*\(/i.test(value);
    });
  return safeDeclarations.join('; ');
}

function sanitizeElementAttributes(element: HTMLElement, tagName: string): void {
  for (const attribute of Array.from(element.attributes)) {
    const attrName = attribute.name.toLowerCase();
    const attrValue = attribute.value.trim();
    let keepAttribute = false;

    if (tagName === 'a' && attrName === 'href') {
      keepAttribute = /^(https?:|mailto:|tel:|#|\/)/i.test(attrValue);
    } else if (tagName === 'a' && attrName === 'title') {
      keepAttribute = true;
    } else if (tagName === 'img' && attrName === 'src') {
      keepAttribute = Boolean(normalizeImageUrl(attrValue));
    } else if (tagName === 'img' && ['alt', 'title', 'loading', 'decoding', 'class'].includes(attrName)) {
      keepAttribute = true;
    } else if (['td', 'th'].includes(tagName) && SAFE_TABLE_ATTRS.has(attrName)) {
      keepAttribute = attrName === 'align' || /^\d{1,3}$/.test(attrValue);
    } else if (['table', 'thead', 'tbody', 'tfoot', 'tr', 'td', 'th', 'col', 'colgroup'].includes(tagName) && attrName === 'style') {
      const safeStyle = sanitizeStyle(attrValue);
      if (safeStyle) {
        element.setAttribute('style', safeStyle);
        keepAttribute = true;
      }
    } else if (['col', 'colgroup'].includes(tagName) && SAFE_COL_ATTRS.has(attrName)) {
      keepAttribute = /^[\w.% -]{1,20}$/.test(attrValue);
    }

    if (!keepAttribute) {
      element.removeAttribute(attribute.name);
    }
  }
}

function rewriteImageElement(element: HTMLElement): void {
  const rawSrc = element.getAttribute('src') || '';
  const resolvedUrl = normalizeImageUrl(rawSrc);
  if (!resolvedUrl) {
    element.replaceWith(window.document.createTextNode(element.getAttribute('alt') || basenameFromPath(rawSrc)));
    return;
  }
  element.setAttribute('src', resolvedUrl);
  element.setAttribute('loading', 'lazy');
  element.setAttribute('decoding', 'async');
  element.className = 'chat-markdown-image';
}

function isInsideElement(node: Node, tagNames: string[]): boolean {
  let current = node.parentElement;
  while (current) {
    if (tagNames.includes(current.tagName.toLowerCase())) return true;
    current = current.parentElement;
  }
  return false;
}

function enhanceChemicalScripts(node: Text): void {
  const value = node.textContent || '';
  CHEMICAL_SCRIPT_PATTERN.lastIndex = 0;
  if (!CHEMICAL_SCRIPT_PATTERN.test(value)) return;
  CHEMICAL_SCRIPT_PATTERN.lastIndex = 0;
  const fragment = window.document.createDocumentFragment();
  let cursor = 0;

  for (const match of value.matchAll(CHEMICAL_SCRIPT_PATTERN)) {
    const index = match.index || 0;
    if (index > cursor) {
      fragment.appendChild(window.document.createTextNode(value.slice(cursor, index)));
    }
    fragment.appendChild(window.document.createTextNode(match[1]));
    const script = window.document.createElement(match[2] === '_' ? 'sub' : 'sup');
    script.textContent = match[3];
    fragment.appendChild(script);
    cursor = index + match[0].length;
  }

  if (cursor < value.length) {
    fragment.appendChild(window.document.createTextNode(value.slice(cursor)));
  }
  node.replaceWith(fragment);
}

function sanitizeNode(node: Node): void {
  if (node.nodeType === Node.TEXT_NODE) {
    if (!isInsideElement(node, ['code', 'pre'])) {
      enhanceChemicalScripts(node as Text);
    }
    return;
  }
  if (node.nodeType !== Node.ELEMENT_NODE) {
    node.parentNode?.removeChild(node);
    return;
  }

  const element = node as HTMLElement;
  const tagName = element.tagName.toLowerCase();
  if (!SAFE_MARKDOWN_TAGS.has(tagName)) {
    const parent = element.parentNode;
    if (!parent) return;
    const movedChildren = Array.from(element.childNodes);
    while (element.firstChild) {
      parent.insertBefore(element.firstChild, element);
    }
    parent.removeChild(element);
    for (const child of movedChildren) {
      sanitizeNode(child);
    }
    return;
  }

  sanitizeElementAttributes(element, tagName);
  if (tagName === 'a') {
    element.setAttribute('target', '_blank');
    element.setAttribute('rel', 'noopener noreferrer');
  }
  if (tagName === 'img') {
    rewriteImageElement(element);
  }

  for (const child of Array.from(element.childNodes)) {
    sanitizeNode(child);
  }
}

function sanitizeMarkdownHtml(html: string): string {
  const template = window.document.createElement('template');
  template.innerHTML = html;
  for (const child of Array.from(template.content.childNodes)) {
    sanitizeNode(child);
  }
  return template.innerHTML;
}

function restoreMathPlaceholders(html: string, placeholders: MathPlaceholder[]): string {
  return placeholders.reduce(
    (currentHtml, item) => currentHtml.replace(new RegExp(escapeRegExp(item.token), 'g'), item.html),
    html,
  );
}

function renderRichMarkdown(markdown: string): string {
  if (!markdown.trim()) return '';
  const protectedMarkdown = protectMath(preprocessMarkdown(markdown));
  const renderedMarkdown = markdownRenderer.render(protectedMarkdown.markdown);
  return restoreMathPlaceholders(sanitizeMarkdownHtml(renderedMarkdown), protectedMarkdown.placeholders);
}
</script>

<template>
  <article class="chat-rich-content" v-html="renderedHtml" />
</template>

<style scoped>
.chat-rich-content {
  color: #475569;
  font-size: 13px;
  line-height: 1.62;
  overflow-wrap: anywhere;
}

.chat-rich-content :deep(p),
.chat-rich-content :deep(blockquote),
.chat-rich-content :deep(ul),
.chat-rich-content :deep(ol),
.chat-rich-content :deep(pre),
.chat-rich-content :deep(table),
.chat-rich-content :deep(.chat-math-block) {
  margin: 0 0 10px;
}

.chat-rich-content :deep(p:last-child),
.chat-rich-content :deep(ul:last-child),
.chat-rich-content :deep(ol:last-child),
.chat-rich-content :deep(pre:last-child),
.chat-rich-content :deep(table:last-child),
.chat-rich-content :deep(.chat-math-block:last-child) {
  margin-bottom: 0;
}

.chat-rich-content :deep(h1),
.chat-rich-content :deep(h2),
.chat-rich-content :deep(h3),
.chat-rich-content :deep(h4),
.chat-rich-content :deep(h5),
.chat-rich-content :deep(h6) {
  margin: 10px 0 6px;
  color: #475569;
  font-size: 13px;
  font-weight: 600;
  line-height: 1.5;
}

.chat-rich-content :deep(ul),
.chat-rich-content :deep(ol) {
  padding-left: 24px;
}

.chat-rich-content :deep(li) {
  margin: 4px 0;
}

.chat-rich-content :deep(table) {
  display: block;
  max-width: 100%;
  overflow-x: auto;
  border-collapse: collapse;
  font-size: 12px;
  line-height: 1.5;
  white-space: nowrap;
}

.chat-rich-content :deep(th),
.chat-rich-content :deep(td) {
  border: 1px solid #d8dee9;
  padding: 6px 8px;
  vertical-align: top;
}

.chat-rich-content :deep(th) {
  background: #f8fafc;
  color: #334155;
  font-weight: 600;
}

.chat-rich-content :deep(blockquote) {
  border-left: 3px solid #cbd5e1;
  background: #f8fafc;
  color: #64748b;
  padding: 8px 10px;
}

.chat-rich-content :deep(code) {
  border-radius: 4px;
  background: #f1f5f9;
  color: #be123c;
  font-family: Consolas, Monaco, 'Courier New', monospace;
  font-size: 12px;
  padding: 1px 4px;
}

.chat-rich-content :deep(pre) {
  overflow: auto;
  border-radius: 6px;
  background: #0f172a;
  color: #e2e8f0;
  padding: 10px 12px;
  white-space: pre-wrap;
}

.chat-rich-content :deep(pre code) {
  background: transparent;
  color: inherit;
  padding: 0;
}

.chat-rich-content :deep(a) {
  color: #2563eb;
  text-decoration: none;
}

.chat-rich-content :deep(a:hover) {
  text-decoration: underline;
}

.chat-rich-content :deep(.chat-markdown-image) {
  display: block;
  max-width: 100%;
  height: auto;
  margin: 8px 0;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
}

.chat-rich-content :deep(.chat-math-inline) {
  display: inline;
}

.chat-rich-content :deep(.chat-math-block) {
  max-width: 100%;
  overflow-x: auto;
  padding: 2px 0;
}

.chat-rich-content :deep(.katex) {
  font-size: 1em;
  line-height: 1.35;
}

.chat-rich-content :deep(sub),
.chat-rich-content :deep(sup) {
  font-size: 0.78em;
  line-height: 0;
}
</style>
