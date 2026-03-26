export type PrismStyleMap = Record<string, Record<string, string | number | undefined>>;

interface PrismThemeOptions {
  fontFamily?: string;
  fontSize?: string;
  lineHeight?: string;
}

export function withTransparentPrismTheme(
  baseTheme: PrismStyleMap,
  options: PrismThemeOptions = {},
): PrismStyleMap {
  const {
    fontFamily = 'var(--vscode-editor-font-family, monospace)',
    fontSize = '12px',
    lineHeight = '1.6',
  } = options;

  return {
    ...baseTheme,
    'pre[class*="language-"]': {
      ...(baseTheme['pre[class*="language-"]'] || {}),
      background: 'transparent',
      margin: 0,
      padding: 0,
      textShadow: 'none',
    },
    'code[class*="language-"]': {
      ...(baseTheme['code[class*="language-"]'] || {}),
      background: 'transparent',
      fontFamily,
      fontSize,
      lineHeight,
      textShadow: 'none',
    },
  };
}
