# Labeling sheet — calibration-01

Read `../protocol.md` first. Label each item **independently** in your own file (`labels/<round>.labeler-<a|b>.csv`): one of `real issue`, `not an issue`, `unclear`, plus an optional note. Do not reorder items, and do not discuss them with the other labeler until you have both finished.

The question: *is this a real problem in the code as written here, something a reasonable maintainer would want changed?*

---

## calibration-01-01

- **Project / case:** `pr-zod-6543`
- **File:** `packages/zod/src/v4/core/parse.ts`, line 99
- **Tool:** ESLINT  ·  **Rule:** `@typescript-eslint/no-explicit-any`
- **Message:** Unexpected any. Specify a different type.

```text
   91 |         issues = undefined as any;
   92 |         ctx = undefined as any;
   93 |       }
   94 |       return error;
   95 |     },
   96 |     set error(e: errors.$ZodError) {
   97 |       error = e;
   98 |       // a replacement makes the getter's branch unreachable, so the captures have to go here too
>  99 |       issues = undefined as any;
  100 |       ctx = undefined as any;
  101 |     },
  102 |   };
  103 | }
  104 | 
  105 | export type $SafeParseAsync = <T extends schemas.$ZodType>(
  106 |   schema: T,
  107 |   value: unknown,
```

---

## calibration-01-02

- **Project / case:** `pr-zod-6543`
- **File:** `packages/zod/src/v4/core/parse.ts`, line 100
- **Tool:** ESLINT  ·  **Rule:** `@typescript-eslint/no-explicit-any`
- **Message:** Unexpected any. Specify a different type.

```text
   92 |         ctx = undefined as any;
   93 |       }
   94 |       return error;
   95 |     },
   96 |     set error(e: errors.$ZodError) {
   97 |       error = e;
   98 |       // a replacement makes the getter's branch unreachable, so the captures have to go here too
   99 |       issues = undefined as any;
> 100 |       ctx = undefined as any;
  101 |     },
  102 |   };
  103 | }
  104 | 
  105 | export type $SafeParseAsync = <T extends schemas.$ZodType>(
  106 |   schema: T,
  107 |   value: unknown,
  108 |   _ctx?: schemas.ParseContext<errors.$ZodIssue>
```

---

## calibration-01-03

- **Project / case:** `pr-axios-11082`
- **File:** `tests/module/esm/tests/helpers/esm-added-types.ts`, line 51
- **Tool:** ESLINT  ·  **Rule:** `@typescript-eslint/no-unused-vars`
- **Message:** 'contentTooLargeStatus' is assigned a value but never used.

```text
  43 |   {}
  44 | );
  45 | const cancelFlag: boolean | undefined = cancel.__CANCEL__;
  46 | const cancelCtor: typeof CanceledError = axios.Cancel;
  47 | const cancelFromAlias = new cancelCtor('from alias');
  48 | 
  49 | const status: HttpStatusCode = HttpStatusCode.WebServerIsDown;
  50 | const unknownErrorStatus: HttpStatusCode = HttpStatusCode.WebServerReturnsAnUnknownError;
> 51 | const contentTooLargeStatus: HttpStatusCode = HttpStatusCode.ContentTooLarge;
  52 | const unprocessableContentStatus: HttpStatusCode = HttpStatusCode.UnprocessableContent;
  53 | 
  54 | class CustomBlob {
  55 |   constructor(_parts?: any[]) {}
  56 | }
  57 | 
  58 | const serializerOptions: FormSerializerOptions = {
  59 |   maxDepth: 2,
```

---

## calibration-01-04

- **Project / case:** `pr-zod-6541`
- **File:** `packages/zod/src/v4/core/json-schema-processors.ts`, line 341
- **Tool:** ESLINT  ·  **Rule:** `@typescript-eslint/no-explicit-any`
- **Message:** Unexpected any. Specify a different type.

```text
  333 |   json.type = "object";
  334 |   json.properties = {};
  335 | 
  336 |   for (const key in shape) {
  337 |     // assignProp so a __proto__ key becomes an own property instead of hitting the inherited setter on the plain {} we build into
  338 |     assignProp(
  339 |       json.properties,
  340 |       key,
> 341 |       processSchema(shape[key]!, ctx as any, {
  342 |         ...params,
  343 |         path: [...params.path, "properties", key],
  344 |       })
  345 |     );
  346 |   }
  347 | 
  348 |   // required keys
  349 |   const allKeys = new Set(Object.keys(shape));
```

---

## calibration-01-05

- **Project / case:** `pr-zod-6541`
- **File:** `packages/zod/src/v4/core/json-schema-processors.ts`, line 734
- **Tool:** ESLINT  ·  **Rule:** `@typescript-eslint/no-explicit-any`
- **Message:** Unexpected any. Specify a different type.

```text
  726 |   seen.ref = def.innerType;
  727 |   if (ctx.io !== "input") return;
  728 |   const value = serializeDefaultValue(def.defaultValue, schema, ctx as ToJSONSchemaContext, json, params);
  729 |   if (value !== UNREPRESENTABLE_DEFAULT) json._prefault = value;
  730 | };
  731 | 
  732 | export const catchProcessor: Processor<schemas.$ZodCatch> = (schema, ctx, json, params) => {
  733 |   const def = schema._zod.def as schemas.$ZodCatchDef;
> 734 |   processSchema(def.innerType, ctx as any, params);
  735 |   const seen = ctx.seen.get(schema)!;
  736 |   seen.ref = def.innerType;
  737 |   let catchValue: any;
  738 |   try {
  739 |     catchValue = def.catchValue(undefined as any);
  740 |   } catch {
  741 |     handleUnrepresentable(schema, ctx, json, params, "Dynamic catch values are not supported in JSON Schema");
  742 |     return;
```

---

## calibration-01-06

- **Project / case:** `pr-axios-11082`
- **File:** `tests/module/cjs/tests/helpers/cjs-added-types.ts`, line 36
- **Tool:** ESLINT  ·  **Rule:** `@typescript-eslint/no-unused-vars`
- **Message:** 'unprocessableContentStatus' is assigned a value but never used.

```text
  28 | );
  29 | const cancelFlag: boolean | undefined = cancel.__CANCEL__;
  30 | const cancelCtor: typeof axios.CanceledError = axios.Cancel;
  31 | const cancelFromAlias = new cancelCtor('from alias');
  32 | 
  33 | const status = axios.HttpStatusCode.WebServerIsDown;
  34 | const unknownErrorStatus = axios.HttpStatusCode.WebServerReturnsAnUnknownError;
  35 | const contentTooLargeStatus = axios.HttpStatusCode.ContentTooLarge;
> 36 | const unprocessableContentStatus = axios.HttpStatusCode.UnprocessableContent;
  37 | 
  38 | class CustomBlob {
  39 |   constructor(_parts?: any[]) {}
  40 | }
  41 | 
  42 | const serializerOptions: axios.FormSerializerOptions = {
  43 |   maxDepth: 2,
  44 |   Blob: CustomBlob,
```

---

## calibration-01-07

- **Project / case:** `pr-zod-6541`
- **File:** `packages/zod/src/v4/core/json-schema-processors.ts`, line 686
- **Tool:** ESLINT  ·  **Rule:** `@typescript-eslint/no-explicit-any`
- **Message:** Unexpected any. Specify a different type.

```text
  678 |     json.nullable = true;
  679 |   } else {
  680 |     json.anyOf = [inner, { type: "null" }];
  681 |   }
  682 | };
  683 | 
  684 | export const nonoptionalProcessor: Processor<schemas.$ZodNonOptional> = (schema, ctx, _json, params) => {
  685 |   const def = schema._zod.def as schemas.$ZodNonOptionalDef;
> 686 |   processSchema(def.innerType, ctx as any, params);
  687 |   const seen = ctx.seen.get(schema)!;
  688 |   seen.ref = def.innerType;
  689 | };
  690 | 
  691 | /** Round-trips a default value through JSON so the emitted schema is guaranteed to be valid JSON.
  692 |  * A BigInt has no reliable encoding, so it goes through `unrepresentable` like any other
  693 |  * unrepresentable value. Returns a sentinel when the caller must not write a default of its own. */
  694 | const UNREPRESENTABLE_DEFAULT = Symbol();
```

---

## calibration-01-08

- **Project / case:** `pr-fastify-7018`
- **File:** `test/internals/validation.test.js`, line 55
- **Tool:** ESLINT  ·  **Rule:** `getter-return`
- **Message:** Expected to return a value in getter 'body'.

```text
  47 |     })
  48 |   }
  49 | }
  50 | 
  51 | test('validate skips a body without a matching content-type schema', t => {
  52 |   const context = { [symbols.bodySchema]: { 'application/json': () => true } }
  53 |   const request = {
  54 |     mediaType: 'text/plain',
> 55 |     get body () {
  56 |       t.assert.fail('an unvalidated body must not be read')
  57 |     }
  58 |   }
  59 | 
  60 |   t.assert.strictEqual(validation.validate(context, request), false)
  61 | })
  62 | 
  63 | test('validate passes null for an undefined request part and preserves other values', t => {
```

---

## calibration-01-09

- **Project / case:** `pr-zod-6543`
- **File:** `packages/zod/src/v4/core/parse.ts`, line 92
- **Tool:** ESLINT  ·  **Rule:** `@typescript-eslint/no-explicit-any`
- **Message:** Unexpected any. Specify a different type.

```text
   84 |   let error: errors.$ZodError | undefined;
   85 |   return {
   86 |     success: false,
   87 |     get error() {
   88 |       if (!error) {
   89 |         error = new Err(issues.map((iss) => util.finalizeIssue(iss, ctx, core.config())));
   90 |         // finalizeIssue drops `input`, so the built error holds nothing; keeping the raw issues past this point pins the parsed value for the life of the result
   91 |         issues = undefined as any;
>  92 |         ctx = undefined as any;
   93 |       }
   94 |       return error;
   95 |     },
   96 |     set error(e: errors.$ZodError) {
   97 |       error = e;
   98 |       // a replacement makes the getter's branch unreachable, so the captures have to go here too
   99 |       issues = undefined as any;
  100 |       ctx = undefined as any;
```

---

## calibration-01-10

- **Project / case:** `pr-zod-6572`
- **File:** `packages/zod/src/v4/classic/tests/cyclic-data.test.ts`, line 974
- **Tool:** ESLINT  ·  **Rule:** `@typescript-eslint/no-explicit-any`
- **Message:** Unexpected any. Specify a different type.

```text
  966 | test("a finished parse pins nothing on the schema", async () => {
  967 |   // es2020 is the target, and its lib predates WeakRef
  968 |   type Weak<T extends object> = { deref(): T | undefined };
  969 |   const { WeakRef: Weak } = globalThis as unknown as { WeakRef: new <T extends object>(target: T) => Weak<T> };
  970 |   // vitest carries no --expose-gc, so reach the collector the way node's own tests do
  971 |   v8.setFlagsFromString("--expose-gc");
  972 |   const gc = vm.runInNewContext("gc") as () => void;
  973 | 
> 974 |   const Node: any = z.object({
  975 |     id: z.number(),
  976 |     get next() {
  977 |       return z.optional(Node);
  978 |     },
  979 |   });
  980 | 
  981 |   const ref = ((): Weak<object> => {
  982 |     const input = { id: 1, next: { id: 2, next: undefined } };
```
