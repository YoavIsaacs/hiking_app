// @vitest-environment node
import { ESLint } from 'eslint'
import tseslint from 'typescript-eslint'
import { describe, expect, it } from 'vitest'

// No node typings in the app tsconfig, so derive the web/ root from the URL.
const WEB_ROOT = decodeURIComponent(new URL('../..', import.meta.url).pathname)
  .replace(/^\/(?=[A-Za-z]:)/, '')
  .replace(/\/$/, '')
const MESSAGE = 'Call the API through src/api/client.ts'

// The repo config (web/eslint.config.js) is used as-is, except that
// type-aware parsing is switched off: the project service rejects virtual
// paths that no tsconfig includes, and the rule under test is syntax-only.
const eslint = new ESLint({
  cwd: WEB_ROOT,
  overrideConfig: [
    {
      files: ['**/*.{ts,tsx}'],
      languageOptions: { parserOptions: { projectService: false } },
    },
    tseslint.configs.disableTypeChecked,
  ],
})

async function lint(code: string, file: string): Promise<string[]> {
  // Virtual path: the file need not exist, but must sit inside the project.
  const [result] = await eslint.lintText(code, {
    filePath: `${WEB_ROOT}/${file}`,
  })
  const messages = result?.messages ?? []
  // A parse failure would make every "no error" assertion pass vacuously.
  expect(messages.filter((m) => m.fatal)).toEqual([])
  return messages
    .filter((m) => m.ruleId === 'no-restricted-syntax')
    .map((m) => m.message)
}

const rawFetchCalls = [
  ['fetch', "export const load = () => fetch('/health')\n"],
  ['window.fetch', "export const load = () => window.fetch('/health')\n"],
  [
    'globalThis.fetch',
    "export const load = () => globalThis.fetch('/health')\n",
  ],
  ['self.fetch', "export const load = () => self.fetch('/health')\n"],
] as const

describe('raw fetch lint rule', () => {
  it.each(rawFetchCalls)(
    '%s outside src/api/ is an error',
    async (_name, code) => {
      expect(await lint(code, 'src/pages/X.tsx')).toEqual([MESSAGE])
    },
  )

  it.each(rawFetchCalls)(
    '%s inside src/api/ is allowed',
    async (_name, code) => {
      expect(await lint(code, 'src/api/x.ts')).toEqual([])
    },
  )

  it('does not flag unrelated calls such as obj.fetchData()', async () => {
    const code =
      'const obj = { fetchData: () => 1, fetch: 2 }\nexport const v = [obj.fetchData(), obj.fetch]\n'
    expect(await lint(code, 'src/pages/X.tsx')).toEqual([])
  })
})
