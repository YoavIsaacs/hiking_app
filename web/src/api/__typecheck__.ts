// Compile-time only: never imported by app code and never executed (excluded
// from coverage). `tsc -b` type-checks it, so a renamed, removed or retyped
// field, path or method in schema.d.ts breaks the build.
import createClient from 'openapi-fetch'
import type { paths } from './schema'

const client = createClient<paths>({ baseUrl: 'http://typecheck.invalid' })

type Equal<A, B> =
  (<T>() => T extends A ? 1 : 2) extends <T>() => T extends B ? 1 : 2
    ? true
    : false
type HttpMethod =
  'get' | 'put' | 'post' | 'delete' | 'options' | 'head' | 'patch' | 'trace'

// Every HTTP method an operation declares on a path.
type MethodsOf<P> = {
  [M in Extract<keyof P, HttpMethod>]-?: P[M] extends undefined ? never : M
}[Extract<keyof P, HttpMethod>]

// One entry per path, one call per declared method. A path or method added to
// the API without a call here is a missing-property error (exhaustiveness);
// an entry for a path or method that no longer exists is an excess-property
// error.
type EveryCall = {
  [P in keyof paths]: { [M in MethodsOf<paths[P]>]: () => Promise<unknown> }
}

export const contractCalls = {
  '/health': {
    get: async () => {
      const { data } = await client.GET('/health')
      if (!data) return undefined
      return data
    },
  },
} satisfies EveryCall

// Field by field: each entry is `true` only if the generated type matches
// exactly, so a rename, removal, addition or retype breaks `tsc`.
type Health = NonNullable<
  Awaited<ReturnType<(typeof contractCalls)['/health']['get']>>
>
export const healthFieldChecks: [
  Equal<Health['status'], 'ok'>,
  Equal<Health['version'], string>,
  Equal<Health['git_sha'], string>,
  Equal<Health['env'], string>,
  Equal<keyof Health, 'status' | 'version' | 'git_sha' | 'env'>,
] = [true, true, true, true, true]
