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
  '/v1/routes/parse': {
    post: async () => {
      const { data, error } = await client.POST('/v1/routes/parse', {
        body: { file: '' },
        bodySerializer: (body) => {
          const form = new FormData()
          form.append('file', body.file)
          return form
        },
      })
      if (error) return { error }
      return data
    },
  },
} satisfies EveryCall

// Field by field: each entry is `true` only if the generated type matches
// exactly, so a rename, removal, addition or retype breaks `tsc`.
// Generic helper only; it names no API type.
type CallResult<F extends () => Promise<unknown>> = NonNullable<
  Awaited<ReturnType<F>>
>
type ProbeFn = (typeof contractCalls)['/health']['get']
export const healthFieldChecks: [
  Equal<CallResult<ProbeFn>['status'], 'ok'>,
  Equal<CallResult<ProbeFn>['version'], string>,
  Equal<CallResult<ProbeFn>['git_sha'], string>,
  Equal<CallResult<ProbeFn>['env'], string>,
  Equal<keyof CallResult<ProbeFn>, 'status' | 'version' | 'git_sha' | 'env'>,
] = [true, true, true, true, true]

// parseRoute: success body and error body, field by field (ADR 0004 section 2).
// Nullable fields are required and `T | null`, never optional.
type Parsed = Extract<
  CallResult<(typeof contractCalls)['/v1/routes/parse']['post']>,
  { points: unknown }
>
type ParseFailure = Extract<
  CallResult<(typeof contractCalls)['/v1/routes/parse']['post']>,
  { error: unknown }
>['error']
type Pt = Parsed['start']
type TrackPt = Parsed['points'][number]
export const parseRouteFieldChecks: [
  Equal<Parsed['name'], string>,
  Equal<Parsed['distance_m'], number>,
  Equal<Parsed['gain_m'], number | null>,
  Equal<Parsed['loss_m'], number | null>,
  Equal<Parsed['min_elev_m'], number | null>,
  Equal<Parsed['max_elev_m'], number | null>,
  Equal<Parsed['high_point'], Pt | null>,
  Equal<Parsed['is_loop'], boolean>,
  Equal<Parsed['has_elevation'], boolean>,
  Equal<Parsed['elevation_source'], 'file' | 'lookup' | 'none'>,
  Equal<Parsed['source_format'], 'trk' | 'rte'>,
  Equal<Parsed['point_count_original'], number>,
  Equal<Parsed['points'], TrackPt[]>,
  Equal<
    keyof Parsed,
    | 'name'
    | 'distance_m'
    | 'gain_m'
    | 'loss_m'
    | 'min_elev_m'
    | 'max_elev_m'
    | 'high_point'
    | 'start'
    | 'end'
    | 'is_loop'
    | 'points'
    | 'has_elevation'
    | 'elevation_source'
    | 'source_format'
    | 'point_count_original'
  >,
  Equal<Parsed['end'], Pt>,
  Equal<Pt['lat'], number>,
  Equal<Pt['lon'], number>,
  Equal<Pt['elev_m'], number | null>,
  Equal<keyof Pt, 'lat' | 'lon' | 'elev_m'>,
  Equal<TrackPt['lat'], number>,
  Equal<TrackPt['lon'], number>,
  Equal<TrackPt['elev_m'], number | null>,
  Equal<TrackPt['dist_m'], number>,
  Equal<keyof TrackPt, 'lat' | 'lon' | 'elev_m' | 'dist_m'>,
] = [
  true,
  true,
  true,
  true,
  true,
  true,
  true,
  true,
  true,
  true,
  true,
  true,
  true,
  true,
  true,
  true,
  true,
  true,
  true,
  true,
  true,
  true,
  true,
  true,
]

export const parseRouteErrorChecks: [
  Equal<
    ParseFailure['code'],
    | 'bad_request'
    | 'not_found'
    | 'method_not_allowed'
    | 'file_too_large'
    | 'invalid_gpx'
    | 'too_many_points'
    | 'too_few_points'
    | 'validation_error'
    | 'http_error'
    | 'internal_error'
  >,
  Equal<ParseFailure['message'], string>,
  Equal<
    ParseFailure['detail'],
    { loc: (string | number)[]; msg: string; type: string }[] | null
  >,
  Equal<keyof ParseFailure, 'code' | 'message' | 'detail'>,
] = [true, true, true, true]
