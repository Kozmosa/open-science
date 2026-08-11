import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import ts from 'typescript';

const frontendRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const sourceRoot = path.join(frontendRoot, 'src');
const catalogRoot = path.join(sourceRoot, 'shared', 'i18n');
// Each indirect argument resolves through a nearby, statically declared MessageKey map.
// New indirect forms must be audited before they can hide catalog reachability from this check.
const allowedIndirectArguments = new Set([
  "CAPABILITY_REASON_KEYS[capability.reason] ?? 'pages.tasks.create.capabilityUnavailable'",
  'preset.labelKey',
  'route.descriptionKey',
  'route.titleKey',
  'statusMessageKey[status]',
  'tKey',
]);

function walk(directory) {
  return fs.readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const entryPath = path.join(directory, entry.name);
    return entry.isDirectory() ? walk(entryPath) : [entryPath];
  });
}

function unwrapExpression(expression) {
  let current = expression;
  while (
    ts.isAsExpression(current)
    || ts.isSatisfiesExpression(current)
    || ts.isParenthesizedExpression(current)
  ) {
    current = current.expression;
  }
  return current;
}

function propertyName(property) {
  if (
    ts.isIdentifier(property.name)
    || ts.isStringLiteral(property.name)
    || ts.isNumericLiteral(property.name)
  ) {
    return property.name.text;
  }
  throw new Error(`Unsupported computed i18n property in ${property.getSourceFile().fileName}`);
}

function collectCatalogLeaves(expression, prefix, leaves) {
  const current = unwrapExpression(expression);
  if (ts.isStringLiteral(current) || ts.isNoSubstitutionTemplateLiteral(current)) {
    leaves.add(prefix);
    return;
  }
  if (!ts.isObjectLiteralExpression(current)) {
    throw new Error(`Unsupported i18n catalog value in ${current.getSourceFile().fileName}`);
  }

  for (const property of current.properties) {
    if (!ts.isPropertyAssignment(property)) {
      throw new Error(`Unsupported i18n catalog property in ${property.getSourceFile().fileName}`);
    }
    const name = propertyName(property);
    collectCatalogLeaves(property.initializer, prefix ? `${prefix}.${name}` : name, leaves);
  }
}

function readCatalog(locale) {
  const localeRoot = path.join(catalogRoot, locale);
  const leaves = new Set();

  for (const filePath of walk(localeRoot)) {
    if (!filePath.endsWith('.ts') || filePath.endsWith(`${path.sep}index.ts`)) continue;

    const sourceFile = ts.createSourceFile(
      filePath,
      fs.readFileSync(filePath, 'utf8'),
      ts.ScriptTarget.Latest,
      true,
      ts.ScriptKind.TS,
    );
    const declarations = new Map();
    let defaultExport;

    for (const statement of sourceFile.statements) {
      if (ts.isVariableStatement(statement)) {
        for (const declaration of statement.declarationList.declarations) {
          if (ts.isIdentifier(declaration.name) && declaration.initializer) {
            declarations.set(declaration.name.text, declaration.initializer);
          }
        }
      } else if (ts.isExportAssignment(statement) && !statement.isExportEquals) {
        defaultExport = statement.expression;
      }
    }

    if (!defaultExport) throw new Error(`Missing default export in ${filePath}`);
    const exportExpression = unwrapExpression(defaultExport);
    const catalogExpression = ts.isIdentifier(exportExpression)
      ? declarations.get(exportExpression.text)
      : exportExpression;
    if (!catalogExpression) throw new Error(`Cannot resolve default export in ${filePath}`);
    collectCatalogLeaves(catalogExpression, '', leaves);
  }

  return leaves;
}

function escapeRegExp(value) {
  return value.replace(/[.*+?^${}()|[\]\\]/gu, '\\$&');
}

function templatePattern(template) {
  let pattern = `^${escapeRegExp(template.head.text)}`;
  for (const span of template.templateSpans) {
    pattern += `[^.]+${escapeRegExp(span.literal.text)}`;
  }
  return new RegExp(`${pattern}$`, 'u');
}

function relative(filePath) {
  return path.relative(frontendRoot, filePath).split(path.sep).join('/');
}

function sourceLocation(sourceFile, node) {
  const position = sourceFile.getLineAndCharacterOfPosition(node.getStart(sourceFile));
  return `${relative(sourceFile.fileName)}:${position.line + 1}`;
}

const englishKeys = readCatalog('en');
const chineseKeys = readCatalog('zh');
const missingChinese = [...englishKeys].filter((key) => !chineseKeys.has(key)).sort();
const missingEnglish = [...chineseKeys].filter((key) => !englishKeys.has(key)).sort();

if (missingChinese.length || missingEnglish.length) {
  if (missingChinese.length) console.error(`Missing Chinese i18n keys:\n${missingChinese.join('\n')}`);
  if (missingEnglish.length) console.error(`Missing English i18n keys:\n${missingEnglish.join('\n')}`);
  process.exitCode = 1;
} else {
  const usedKeys = new Set();
  const unmatchedTemplates = [];
  const unauditedIndirectArguments = [];
  const sourceFiles = walk(sourceRoot).filter((filePath) => {
    if (!/\.(?:ts|tsx)$/u.test(filePath)) return false;
    return !filePath.startsWith(path.join(catalogRoot, 'en') + path.sep)
      && !filePath.startsWith(path.join(catalogRoot, 'zh') + path.sep);
  });

  for (const filePath of sourceFiles) {
    const sourceFile = ts.createSourceFile(
      filePath,
      fs.readFileSync(filePath, 'utf8'),
      ts.ScriptTarget.Latest,
      true,
      filePath.endsWith('.tsx') ? ts.ScriptKind.TSX : ts.ScriptKind.TS,
    );

    function visit(node) {
      if (ts.isStringLiteral(node) || ts.isNoSubstitutionTemplateLiteral(node)) {
        if (englishKeys.has(node.text)) usedKeys.add(node.text);
      }

      if (
        ts.isCallExpression(node)
        && ts.isIdentifier(node.expression)
        && node.expression.text === 't'
        && node.arguments.length > 0
      ) {
        const argument = node.arguments[0];
        if (ts.isTemplateExpression(argument)) {
          const pattern = templatePattern(argument);
          const matches = [...englishKeys].filter((key) => pattern.test(key));
          if (matches.length === 0) {
            unmatchedTemplates.push(`${sourceLocation(sourceFile, argument)} ${argument.getText(sourceFile)}`);
          } else {
            for (const key of matches) usedKeys.add(key);
          }
        } else if (
          !ts.isStringLiteral(argument)
          && !ts.isNoSubstitutionTemplateLiteral(argument)
          && !allowedIndirectArguments.has(argument.getText(sourceFile))
        ) {
          unauditedIndirectArguments.push(
            `${sourceLocation(sourceFile, argument)} ${argument.getText(sourceFile)}`,
          );
        }
      }

      ts.forEachChild(node, visit);
    }

    visit(sourceFile);
  }

  const orphanKeys = [...englishKeys].filter((key) => !usedKeys.has(key)).sort();
  if (unmatchedTemplates.length) {
    console.error(`Dynamic i18n templates without catalog matches:\n${unmatchedTemplates.join('\n')}`);
    process.exitCode = 1;
  }
  if (unauditedIndirectArguments.length) {
    console.error(
      `Indirect i18n arguments requiring an explicit audit:\n${unauditedIndirectArguments.join('\n')}`,
    );
    process.exitCode = 1;
  }
  if (orphanKeys.length) {
    console.error(`Unused i18n keys:\n${orphanKeys.join('\n')}`);
    process.exitCode = 1;
  }
  if (!process.exitCode) {
    console.log(`i18n usage check passed (${englishKeys.size} keys)`);
  }
}
