# Labeling sheet — main-01

Read `../protocol.md` first. Label each item **independently** in your own file (`labels/<round>.labeler-<a|b>.csv`): one of `real issue`, `not an issue`, `unclear`, plus an optional note. Do not reorder items, and do not discuss them with the other labeler until you have both finished.

The question: *is this a real problem in the code as written here, something a reasonable maintainer would want changed?*

---

## main-01-01

- **Project / case:** `pr-zod-6541`
- **File:** `packages/zod/src/v4/core/json-schema-processors.ts`, line 447
- **Tool:** ESLINT  ·  **Rule:** `@typescript-eslint/no-explicit-any`
- **Message:** Unexpected any. Specify a different type.

```text
  439 |     json.oneOf = options;
  440 |   } else {
  441 |     json.anyOf = options;
  442 |   }
  443 | };
  444 | 
  445 | export const intersectionProcessor: Processor<schemas.$ZodIntersection> = (schema, ctx, json, params) => {
  446 |   const def = schema._zod.def as schemas.$ZodIntersectionDef;
> 447 |   const a = processSchema(def.left, ctx as any, {
  448 |     ...params,
  449 |     path: [...params.path, "allOf", 0],
  450 |   });
  451 |   const b = processSchema(def.right, ctx as any, {
  452 |     ...params,
  453 |     path: [...params.path, "allOf", 1],
  454 |   });
  455 | 
```

---

## main-01-02

- **Project / case:** `pr-zod-6541`
- **File:** `packages/zod/src/v4/core/json-schema-processors.ts`, line 297
- **Tool:** ESLINT  ·  **Rule:** `@typescript-eslint/no-explicit-any`
- **Message:** Unexpected any. Specify a different type.

```text
  289 | export const arrayProcessor: Processor<schemas.$ZodArray> = (schema, ctx, _json, params) => {
  290 |   const json = _json as JSONSchema.ArraySchema;
  291 |   const def = schema._zod.def as schemas.$ZodArrayDef;
  292 |   const { minimum, maximum } = schema._zod.bag;
  293 |   if (typeof minimum === "number") json.minItems = minimum;
  294 |   if (typeof maximum === "number") json.maxItems = maximum;
  295 | 
  296 |   json.type = "array";
> 297 |   json.items = processSchema(def.element, ctx as any, {
  298 |     ...params,
  299 |     path: [...params.path, "items"],
  300 |   });
  301 | };
  302 | 
  303 | // Transform and catch set `optin = "optional"` at runtime so the parser lets them observe an
  304 | // absent key, but their declared input type stays required. An input JSON Schema describes the
  305 | // declared type, so resolve past them to the schema that actually carries the optionality.
```

---

## main-01-03

- **Project / case:** `pr-zod-6539`
- **File:** `packages/zod/src/v4/core/util.ts`, line 105
- **Tool:** ESLINT  ·  **Rule:** `@typescript-eslint/no-explicit-any`
- **Message:** Unexpected any. Specify a different type.

```text
   97 | type ToZodKeyMismatch<Expected, Received> = schemas.$ZodType & {
   98 |   "types do not match": { expected: Expected; received: Received };
   99 | };
  100 | 
  101 | // An enum reference and the union of exactly its members are mutually assignable but not identical, so `AssertEqual` alone rejects `z.enum(SomeEnum)` against a `SomeEnum` target. Unioning each side with a private dummy forces the union to be rebuilt, which collapses that one difference and nothing else — plain literals against an enum, member subsets, brands and `any` all still fail. The symbol is not exported, so no user type can smuggle it in and cancel a real difference.
  102 | declare const toZodDummy: unique symbol;
  103 | 
  104 | // Homomorphic, so `readonly` and optional modifiers survive the rebuild and only leaves are normalized. An intersection flattens here, which is why an intersection target and the flat object with the same keys match each other. A callable stops the walk because `keyof` a function is `never`, so mapping one would erase its signature and make every function compare equal.
> 105 | type ToZodNormalize<T> = [T] extends [(...args: any[]) => any]
  106 |   ? T
  107 |   : [T] extends [object]
  108 |     ? { [K in keyof T]: ToZodNormalize<T[K]> }
  109 |     : T | typeof toZodDummy;
  110 | 
  111 | type ToZodEqual<Output, T> = AssertEqual<Output, T> extends true
  112 |   ? true
  113 |   : IsAny<Output> extends true
```

---

## main-01-04

- **Project / case:** `mut-validator-isstrongpassword-l05`
- **File:** `src/lib/isStrongPassword.js`, line 66
- **Tool:** ESLINT  ·  **Rule:** `no-unused-vars`
- **Message:** 'scorePassword' is defined but never used.

```text
  58 |       analysis.numberCount += charMap[char];
  59 |     } else if (symbolRegex.test(char)) {
  60 |       analysis.symbolCount += charMap[char];
  61 |     }
  62 |   });
  63 |   return analysis;
  64 | }
  65 | 
> 66 | function scorePassword(analysis, scoringOptions) {
  67 |   let points = 0;
  68 |   points += analysis.uniqueChars * scoringOptions.pointsPerUnique;
  69 |   points += (analysis.length - analysis.uniqueChars) * scoringOptions.pointsPerRepeat;
  70 |   if (analysis.lowercaseCount > 0) {
  71 |     points += scoringOptions.pointsForContainingLower;
  72 |   }
  73 |   if (analysis.uppercaseCount > 0) {
  74 |     points += scoringOptions.pointsForContainingUpper;
```

---

## main-01-05

- **Project / case:** `pr-zod-6541`
- **File:** `packages/zod/src/v4/core/json-schema-processors.ts`, line 780
- **Tool:** ESLINT  ·  **Rule:** `@typescript-eslint/no-explicit-any`
- **Message:** Unexpected any. Specify a different type.

```text
  772 |   const def = schema._zod.def as schemas.$ZodOptionalDef;
  773 |   processSchema(def.innerType, ctx as any, params);
  774 |   const seen = ctx.seen.get(schema)!;
  775 |   seen.ref = def.innerType;
  776 | };
  777 | 
  778 | export const lazyProcessor: Processor<schemas.$ZodLazy> = (schema, ctx, _json, params) => {
  779 |   const innerType = (schema as schemas.$ZodLazy)._zod.innerType;
> 780 |   processSchema(innerType, ctx as any, params);
  781 |   const seen = ctx.seen.get(schema)!;
  782 |   seen.ref = innerType;
  783 | };
  784 | 
  785 | // ==================== ALL PROCESSORS ====================
  786 | 
  787 | export const allProcessors: Record<string, Processor<any>> = {
  788 |   string: stringProcessor,
```

---

## main-01-06

- **Project / case:** `pr-fastify-7012`
- **File:** `test/content-type-parser-async-context.test.js`, line 55
- **Tool:** ESLINT  ·  **Rule:** `no-unused-vars`
- **Message:** 'reply' is defined but never used.

```text
  47 |     t.assert.deepStrictEqual(storage.getStore(), { id: request.headers['x-request-id'] })
  48 |     t.assert.ok(resources.has(executionAsyncId()))
  49 |   }
  50 | 
  51 |   app.setErrorHandler((error, request, reply) => {
  52 |     assertContext(request)
  53 |     reply.code(400).send({ error: error.message, id: storage.getStore().id })
  54 |   })
> 55 |   app.post('/', (request, reply) => {
  56 |     assertContext(request)
  57 |     return { body: request.body, id: storage.getStore().id }
  58 |   })
  59 | 
  60 |   const responses = await Promise.all(['first', 'second', 'error'].map(id => app.inject({
  61 |     method: 'POST',
  62 |     url: '/',
  63 |     headers: { 'content-type': 'application/custom', 'x-request-id': id },
```

---

## main-01-07

- **Project / case:** `pr-zod-6541`
- **File:** `packages/zod/src/v4/core/json-schema-processors.ts`, line 724
- **Tool:** ESLINT  ·  **Rule:** `@typescript-eslint/no-explicit-any`
- **Message:** Unexpected any. Specify a different type.

```text
  716 |   const seen = ctx.seen.get(schema)!;
  717 |   seen.ref = def.innerType;
  718 |   const value = serializeDefaultValue(def.defaultValue, schema, ctx as ToJSONSchemaContext, json, params);
  719 |   if (value !== UNREPRESENTABLE_DEFAULT) json.default = value;
  720 | };
  721 | 
  722 | export const prefaultProcessor: Processor<schemas.$ZodPrefault> = (schema, ctx, json, params) => {
  723 |   const def = schema._zod.def as schemas.$ZodPrefaultDef;
> 724 |   processSchema(def.innerType, ctx as any, params);
  725 |   const seen = ctx.seen.get(schema)!;
  726 |   seen.ref = def.innerType;
  727 |   if (ctx.io !== "input") return;
  728 |   const value = serializeDefaultValue(def.defaultValue, schema, ctx as ToJSONSchemaContext, json, params);
  729 |   if (value !== UNREPRESENTABLE_DEFAULT) json._prefault = value;
  730 | };
  731 | 
  732 | export const catchProcessor: Processor<schemas.$ZodCatch> = (schema, ctx, json, params) => {
```

---

## main-01-08

- **Project / case:** `pr-zod-6541`
- **File:** `packages/zod/src/v4/core/json-schema-processors.ts`, line 758
- **Tool:** ESLINT  ·  **Rule:** `@typescript-eslint/no-explicit-any`
- **Message:** Unexpected any. Specify a different type.

```text
  750 |   const innerType = ctx.io === "input" ? (inIsTransform ? def.out : def.in) : def.out;
  751 |   processSchema(innerType, ctx as any, params);
  752 |   const seen = ctx.seen.get(schema)!;
  753 |   seen.ref = innerType;
  754 | };
  755 | 
  756 | export const readonlyProcessor: Processor<schemas.$ZodReadonly> = (schema, ctx, json, params) => {
  757 |   const def = schema._zod.def as schemas.$ZodReadonlyDef;
> 758 |   processSchema(def.innerType, ctx as any, params);
  759 |   const seen = ctx.seen.get(schema)!;
  760 |   seen.ref = def.innerType;
  761 |   json.readOnly = true;
  762 | };
  763 | 
  764 | export const promiseProcessor: Processor<schemas.$ZodPromise> = (schema, ctx, _json, params) => {
  765 |   const def = schema._zod.def as schemas.$ZodPromiseDef;
  766 |   processSchema(def.innerType, ctx as any, params);
```

---

## main-01-09

- **Project / case:** `pr-zod-6541`
- **File:** `packages/zod/src/v4/core/json-schema-processors.ts`, line 885
- **Tool:** ESLINT  ·  **Rule:** `@typescript-eslint/no-explicit-any`
- **Message:** Unexpected any. Specify a different type.

```text
  877 |       };
  878 |     }
  879 | 
  880 |     return { schemas };
  881 |   }
  882 | 
  883 |   // Single schema case
  884 |   const ctx = initializeContext({ ...params, processors: allProcessors });
> 885 |   processSchema(input, ctx as any);
  886 |   extractDefs(ctx as any, input);
  887 |   return finalize(ctx as any, input);
  888 | }
```

---

## main-01-10

- **Project / case:** `pr-axios-11082`
- **File:** `tests/module/esm/tests/helpers/esm-added-types.ts`, line 52
- **Tool:** ESLINT  ·  **Rule:** `@typescript-eslint/no-unused-vars`
- **Message:** 'unprocessableContentStatus' is assigned a value but never used.

```text
  44 | );
  45 | const cancelFlag: boolean | undefined = cancel.__CANCEL__;
  46 | const cancelCtor: typeof CanceledError = axios.Cancel;
  47 | const cancelFromAlias = new cancelCtor('from alias');
  48 | 
  49 | const status: HttpStatusCode = HttpStatusCode.WebServerIsDown;
  50 | const unknownErrorStatus: HttpStatusCode = HttpStatusCode.WebServerReturnsAnUnknownError;
  51 | const contentTooLargeStatus: HttpStatusCode = HttpStatusCode.ContentTooLarge;
> 52 | const unprocessableContentStatus: HttpStatusCode = HttpStatusCode.UnprocessableContent;
  53 | 
  54 | class CustomBlob {
  55 |   constructor(_parts?: any[]) {}
  56 | }
  57 | 
  58 | const serializerOptions: FormSerializerOptions = {
  59 |   maxDepth: 2,
  60 |   Blob: CustomBlob,
```

---

## main-01-11

- **Project / case:** `pr-zod-6541`
- **File:** `packages/zod/src/v4/core/json-schema-processors.ts`, line 433
- **Tool:** ESLINT  ·  **Rule:** `@typescript-eslint/no-explicit-any`
- **Message:** Unexpected any. Specify a different type.

```text
  425 |   if (required.length > 0) json.required = required;
  426 | };
  427 | 
  428 | export const unionProcessor: Processor<schemas.$ZodUnion> = (schema, ctx, json, params) => {
  429 |   const def = schema._zod.def as schemas.$ZodUnionDef;
  430 |   // Exclusive unions (inclusive === false) use oneOf (exactly one match) instead of anyOf (one or more matches). This includes both z.xor() and discriminated unions
  431 |   const isExclusive = def.inclusive === false;
  432 |   const options = def.options.map((x, i) =>
> 433 |     processSchema(x, ctx as any, {
  434 |       ...params,
  435 |       path: [...params.path, isExclusive ? "oneOf" : "anyOf", i],
  436 |     })
  437 |   );
  438 |   if (isExclusive) {
  439 |     json.oneOf = options;
  440 |   } else {
  441 |     json.anyOf = options;
```

---

## main-01-12

- **Project / case:** `mut-validator-isean-l08`
- **File:** `src/lib/isEAN.js`, line 23
- **Tool:** ESLINT  ·  **Rule:** `no-unused-vars`
- **Message:** 'LENGTH_EAN_14' is assigned a value but never used.

```text
  15 | import assertString from './util/assertString';
  16 | 
  17 | /**
  18 |  * Define EAN Lengths; 8 for EAN-8; 13 for EAN-13; 14 for EAN-14
  19 |  * and Regular Expression for valid EANs (EAN-8, EAN-13, EAN-14),
  20 |  * with exact numeric matching of 8 or 13 or 14 digits [0-9]
  21 |  */
  22 | const LENGTH_EAN_8 = 8;
> 23 | const LENGTH_EAN_14 = 14;
  24 | const validEanRegex = /^(\d{8}|\d{13}|\d{14})$/;
  25 | 
  26 | 
  27 | /**
  28 |  * Get position weight given:
  29 |  * EAN length and digit index/position
  30 |  *
  31 |  * @param {number} length
```

---

## main-01-13

- **Project / case:** `pr-zod-6541`
- **File:** `packages/zod/src/v4/core/json-schema-processors.ts`, line 373
- **Tool:** ESLINT  ·  **Rule:** `@typescript-eslint/no-explicit-any`
- **Message:** Unexpected any. Specify a different type.

```text
  365 |   // catchall
  366 |   if (def.catchall?._zod.def.type === "never") {
  367 |     // strict
  368 |     json.additionalProperties = false;
  369 |   } else if (!def.catchall) {
  370 |     // regular
  371 |     if (ctx.io === "output") json.additionalProperties = false;
  372 |   } else if (def.catchall) {
> 373 |     json.additionalProperties = processSchema(def.catchall, ctx as any, {
  374 |       ...params,
  375 |       path: [...params.path, "additionalProperties"],
  376 |     });
  377 |   }
  378 | };
  379 | 
  380 | // asserts named properties in place and passes everything else through, so no additionalProperties constraint is emitted
  381 | export const propertiesProcessor: Processor<schemas.$ZodProperties> = (schema, ctx, _json, params) => {
```

---

## main-01-14

- **Project / case:** `mut-validator-isean-l08`
- **File:** `src/lib/isEAN.js`, line 22
- **Tool:** ESLINT  ·  **Rule:** `no-unused-vars`
- **Message:** 'LENGTH_EAN_8' is assigned a value but never used.

```text
  14 | 
  15 | import assertString from './util/assertString';
  16 | 
  17 | /**
  18 |  * Define EAN Lengths; 8 for EAN-8; 13 for EAN-13; 14 for EAN-14
  19 |  * and Regular Expression for valid EANs (EAN-8, EAN-13, EAN-14),
  20 |  * with exact numeric matching of 8 or 13 or 14 digits [0-9]
  21 |  */
> 22 | const LENGTH_EAN_8 = 8;
  23 | const LENGTH_EAN_14 = 14;
  24 | const validEanRegex = /^(\d{8}|\d{13}|\d{14})$/;
  25 | 
  26 | 
  27 | /**
  28 |  * Get position weight given:
  29 |  * EAN length and digit index/position
  30 |  *
```

---

## main-01-15

- **Project / case:** `pr-zod-6541`
- **File:** `packages/zod/src/v4/core/json-schema-processors.ts`, line 766
- **Tool:** ESLINT  ·  **Rule:** `@typescript-eslint/no-explicit-any`
- **Message:** Unexpected any. Specify a different type.

```text
  758 |   processSchema(def.innerType, ctx as any, params);
  759 |   const seen = ctx.seen.get(schema)!;
  760 |   seen.ref = def.innerType;
  761 |   json.readOnly = true;
  762 | };
  763 | 
  764 | export const promiseProcessor: Processor<schemas.$ZodPromise> = (schema, ctx, _json, params) => {
  765 |   const def = schema._zod.def as schemas.$ZodPromiseDef;
> 766 |   processSchema(def.innerType, ctx as any, params);
  767 |   const seen = ctx.seen.get(schema)!;
  768 |   seen.ref = def.innerType;
  769 | };
  770 | 
  771 | export const optionalProcessor: Processor<schemas.$ZodOptional> = (schema, ctx, _json, params) => {
  772 |   const def = schema._zod.def as schemas.$ZodOptionalDef;
  773 |   processSchema(def.innerType, ctx as any, params);
  774 |   const seen = ctx.seen.get(schema)!;
```

---

## main-01-16

- **Project / case:** `pr-zod-6541`
- **File:** `packages/zod/src/v4/core/json-schema-processors.ts`, line 476
- **Tool:** ESLINT  ·  **Rule:** `@typescript-eslint/no-explicit-any`
- **Message:** Unexpected any. Specify a different type.

```text
  468 |   const def = schema._zod.def as schemas.$ZodTupleDef;
  469 |   json.type = "array";
  470 | 
  471 |   const prefixPath = ctx.target === "draft-2020-12" ? "prefixItems" : "items";
  472 |   const restPath =
  473 |     ctx.target === "draft-2020-12" ? "items" : ctx.target === "openapi-3.0" ? "items" : "additionalItems";
  474 | 
  475 |   const prefixItems = def.items.map((x, i) =>
> 476 |     processSchema(x, ctx as any, {
  477 |       ...params,
  478 |       path: [...params.path, prefixPath, i],
  479 |     })
  480 |   );
  481 |   const rest = def.rest
  482 |     ? processSchema(def.rest, ctx as any, {
  483 |         ...params,
  484 |         path: [...params.path, restPath, ...(ctx.target === "openapi-3.0" ? [def.items.length] : [])],
```

---

## main-01-17

- **Project / case:** `pr-zod-6541`
- **File:** `packages/zod/src/v4/core/json-schema-processors.ts`, line 482
- **Tool:** ESLINT  ·  **Rule:** `@typescript-eslint/no-explicit-any`
- **Message:** Unexpected any. Specify a different type.

```text
  474 | 
  475 |   const prefixItems = def.items.map((x, i) =>
  476 |     processSchema(x, ctx as any, {
  477 |       ...params,
  478 |       path: [...params.path, prefixPath, i],
  479 |     })
  480 |   );
  481 |   const rest = def.rest
> 482 |     ? processSchema(def.rest, ctx as any, {
  483 |         ...params,
  484 |         path: [...params.path, restPath, ...(ctx.target === "openapi-3.0" ? [def.items.length] : [])],
  485 |       })
  486 |     : null;
  487 | 
  488 |   let minItems = def.items.length;
  489 |   while (minItems > 0) {
  490 |     const item = def.items[minItems - 1] as schemas.$ZodType;
```

---

## main-01-18

- **Project / case:** `pr-zod-6541`
- **File:** `packages/zod/src/v4/core/json-schema-processors.ts`, line 773
- **Tool:** ESLINT  ·  **Rule:** `@typescript-eslint/no-explicit-any`
- **Message:** Unexpected any. Specify a different type.

```text
  765 |   const def = schema._zod.def as schemas.$ZodPromiseDef;
  766 |   processSchema(def.innerType, ctx as any, params);
  767 |   const seen = ctx.seen.get(schema)!;
  768 |   seen.ref = def.innerType;
  769 | };
  770 | 
  771 | export const optionalProcessor: Processor<schemas.$ZodOptional> = (schema, ctx, _json, params) => {
  772 |   const def = schema._zod.def as schemas.$ZodOptionalDef;
> 773 |   processSchema(def.innerType, ctx as any, params);
  774 |   const seen = ctx.seen.get(schema)!;
  775 |   seen.ref = def.innerType;
  776 | };
  777 | 
  778 | export const lazyProcessor: Processor<schemas.$ZodLazy> = (schema, ctx, _json, params) => {
  779 |   const innerType = (schema as schemas.$ZodLazy)._zod.innerType;
  780 |   processSchema(innerType, ctx as any, params);
  781 |   const seen = ctx.seen.get(schema)!;
```

---

## main-01-19

- **Project / case:** `pr-zod-6541`
- **File:** `packages/zod/src/v4/core/json-schema-processors.ts`, line 651
- **Tool:** ESLINT  ·  **Rule:** `@typescript-eslint/no-explicit-any`
- **Message:** Unexpected any. Specify a different type.

```text
  643 |       let pending = pendingRecords.get(ctx);
  644 |       if (!pending) {
  645 |         pending = [];
  646 |         pendingRecords.set(ctx, pending);
  647 |         ctx.deferred.push(() => rewriteKeyNames(ctx));
  648 |       }
  649 |       pending.push(schema);
  650 |     }
> 651 |     json.additionalProperties = processSchema(def.valueType, ctx as any, {
  652 |       ...params,
  653 |       path: [...params.path, "additionalProperties"],
  654 |     });
  655 |   }
  656 | 
  657 |   // Add required for keys with discrete values (enum, literal, etc.)
  658 |   const keyValues = keyType._zod.values;
  659 |   // Every key shares one value schema, so an optional-in value makes the whole key set omittable on input. Output keeps them: the exhaustive branch assigns every key, even one whose value came back undefined.
```

---

## main-01-20

- **Project / case:** `pr-zod-6541`
- **File:** `packages/zod/src/v4/core/json-schema-processors.ts`, line 451
- **Tool:** ESLINT  ·  **Rule:** `@typescript-eslint/no-explicit-any`
- **Message:** Unexpected any. Specify a different type.

```text
  443 | };
  444 | 
  445 | export const intersectionProcessor: Processor<schemas.$ZodIntersection> = (schema, ctx, json, params) => {
  446 |   const def = schema._zod.def as schemas.$ZodIntersectionDef;
  447 |   const a = processSchema(def.left, ctx as any, {
  448 |     ...params,
  449 |     path: [...params.path, "allOf", 0],
  450 |   });
> 451 |   const b = processSchema(def.right, ctx as any, {
  452 |     ...params,
  453 |     path: [...params.path, "allOf", 1],
  454 |   });
  455 | 
  456 |   const isSimpleIntersection = (val: any) => "allOf" in val && Object.keys(val).length === 1;
  457 |   const allOf = [
  458 |     ...(isSimpleIntersection(a) ? (a.allOf as any[]) : [a]),
  459 |     ...(isSimpleIntersection(b) ? (b.allOf as any[]) : [b]),
```

---

## main-01-21

- **Project / case:** `pr-zod-6541`
- **File:** `packages/zod/src/v4/core/json-schema-processors.ts`, line 639
- **Tool:** ESLINT  ·  **Rule:** `@typescript-eslint/no-explicit-any`
- **Message:** Unexpected any. Specify a different type.

```text
  631 |     });
  632 |     json.patternProperties = {};
  633 |     for (const pattern of patterns) {
  634 |       assignProp(json.patternProperties, exactPattern(pattern).source, valueSchema);
  635 |     }
  636 |   } else {
  637 |     // Default behavior: use propertyNames + additionalProperties
  638 |     if (ctx.target === "draft-07" || ctx.target === "draft-2020-12") {
> 639 |       json.propertyNames = processSchema(def.keyType, ctx as any, {
  640 |         ...params,
  641 |         path: [...params.path, "propertyNames"],
  642 |       });
  643 |       let pending = pendingRecords.get(ctx);
  644 |       if (!pending) {
  645 |         pending = [];
  646 |         pendingRecords.set(ctx, pending);
  647 |         ctx.deferred.push(() => rewriteKeyNames(ctx));
```

---

## main-01-22

- **Project / case:** `pr-zod-6541`
- **File:** `packages/zod/src/v4/core/json-schema-processors.ts`, line 751
- **Tool:** ESLINT  ·  **Rule:** `@typescript-eslint/no-explicit-any`
- **Message:** Unexpected any. Specify a different type.

```text
  743 |   }
  744 |   json.default = catchValue;
  745 | };
  746 | 
  747 | export const pipeProcessor: Processor<schemas.$ZodPipe> = (schema, ctx, _json, params) => {
  748 |   const def = schema._zod.def as schemas.$ZodPipeDef;
  749 |   const inIsTransform = def.in._zod.traits.has("$ZodTransform");
  750 |   const innerType = ctx.io === "input" ? (inIsTransform ? def.out : def.in) : def.out;
> 751 |   processSchema(innerType, ctx as any, params);
  752 |   const seen = ctx.seen.get(schema)!;
  753 |   seen.ref = innerType;
  754 | };
  755 | 
  756 | export const readonlyProcessor: Processor<schemas.$ZodReadonly> = (schema, ctx, json, params) => {
  757 |   const def = schema._zod.def as schemas.$ZodReadonlyDef;
  758 |   processSchema(def.innerType, ctx as any, params);
  759 |   const seen = ctx.seen.get(schema)!;
```

---

## main-01-23

- **Project / case:** `pr-zod-6541`
- **File:** `packages/zod/src/v4/core/json-schema-processors.ts`, line 674
- **Tool:** ESLINT  ·  **Rule:** `@typescript-eslint/no-explicit-any`
- **Message:** Unexpected any. Specify a different type.

```text
  666 |     if (validKeyValues.length > 0) {
  667 |       json.required = validKeyValues.map(String);
  668 |     }
  669 |   }
  670 | };
  671 | 
  672 | export const nullableProcessor: Processor<schemas.$ZodNullable> = (schema, ctx, json, params) => {
  673 |   const def = schema._zod.def as schemas.$ZodNullableDef;
> 674 |   const inner = processSchema(def.innerType, ctx as any, params);
  675 |   const seen = ctx.seen.get(schema)!;
  676 |   if (ctx.target === "openapi-3.0") {
  677 |     seen.ref = def.innerType;
  678 |     json.nullable = true;
  679 |   } else {
  680 |     json.anyOf = [inner, { type: "null" }];
  681 |   }
  682 | };
```

---

## main-01-24

- **Project / case:** `pr-zod-6539`
- **File:** `packages/zod/src/v4/core/util.ts`, line 105
- **Tool:** ESLINT  ·  **Rule:** `@typescript-eslint/no-explicit-any`
- **Message:** Unexpected any. Specify a different type.

```text
   97 | type ToZodKeyMismatch<Expected, Received> = schemas.$ZodType & {
   98 |   "types do not match": { expected: Expected; received: Received };
   99 | };
  100 | 
  101 | // An enum reference and the union of exactly its members are mutually assignable but not identical, so `AssertEqual` alone rejects `z.enum(SomeEnum)` against a `SomeEnum` target. Unioning each side with a private dummy forces the union to be rebuilt, which collapses that one difference and nothing else — plain literals against an enum, member subsets, brands and `any` all still fail. The symbol is not exported, so no user type can smuggle it in and cancel a real difference.
  102 | declare const toZodDummy: unique symbol;
  103 | 
  104 | // Homomorphic, so `readonly` and optional modifiers survive the rebuild and only leaves are normalized. An intersection flattens here, which is why an intersection target and the flat object with the same keys match each other. A callable stops the walk because `keyof` a function is `never`, so mapping one would erase its signature and make every function compare equal.
> 105 | type ToZodNormalize<T> = [T] extends [(...args: any[]) => any]
  106 |   ? T
  107 |   : [T] extends [object]
  108 |     ? { [K in keyof T]: ToZodNormalize<T[K]> }
  109 |     : T | typeof toZodDummy;
  110 | 
  111 | type ToZodEqual<Output, T> = AssertEqual<Output, T> extends true
  112 |   ? true
  113 |   : IsAny<Output> extends true
```

---

## main-01-25

- **Project / case:** `pr-zod-6543`
- **File:** `packages/zod/src/v4/core/parse.ts`, line 91
- **Tool:** ESLINT  ·  **Rule:** `@typescript-eslint/no-explicit-any`
- **Message:** Unexpected any. Specify a different type.

```text
   83 | function failure(Err: $ZodErrorClass, issues: errors.$ZodRawIssue[], ctx: schemas.ParseContextInternal): any {
   84 |   let error: errors.$ZodError | undefined;
   85 |   return {
   86 |     success: false,
   87 |     get error() {
   88 |       if (!error) {
   89 |         error = new Err(issues.map((iss) => util.finalizeIssue(iss, ctx, core.config())));
   90 |         // finalizeIssue drops `input`, so the built error holds nothing; keeping the raw issues past this point pins the parsed value for the life of the result
>  91 |         issues = undefined as any;
   92 |         ctx = undefined as any;
   93 |       }
   94 |       return error;
   95 |     },
   96 |     set error(e: errors.$ZodError) {
   97 |       error = e;
   98 |       // a replacement makes the getter's branch unreachable, so the captures have to go here too
   99 |       issues = undefined as any;
```

---

## main-01-26

- **Project / case:** `pr-zod-6541`
- **File:** `packages/zod/src/v4/core/json-schema-processors.ts`, line 715
- **Tool:** ESLINT  ·  **Rule:** `@typescript-eslint/no-explicit-any`
- **Message:** Unexpected any. Specify a different type.

```text
  707 |   });
  708 |   if (!unrepresentable) return JSON.parse(serialized);
  709 |   handleUnrepresentable(schema, ctx, json, params, "BigInt defaults cannot be represented in JSON Schema");
  710 |   return UNREPRESENTABLE_DEFAULT;
  711 | }
  712 | 
  713 | export const defaultProcessor: Processor<schemas.$ZodDefault> = (schema, ctx, json, params) => {
  714 |   const def = schema._zod.def as schemas.$ZodDefaultDef;
> 715 |   processSchema(def.innerType, ctx as any, params);
  716 |   const seen = ctx.seen.get(schema)!;
  717 |   seen.ref = def.innerType;
  718 |   const value = serializeDefaultValue(def.defaultValue, schema, ctx as ToJSONSchemaContext, json, params);
  719 |   if (value !== UNREPRESENTABLE_DEFAULT) json.default = value;
  720 | };
  721 | 
  722 | export const prefaultProcessor: Processor<schemas.$ZodPrefault> = (schema, ctx, json, params) => {
  723 |   const def = schema._zod.def as schemas.$ZodPrefaultDef;
```

---

## main-01-27

- **Project / case:** `pr-zod-6541`
- **File:** `packages/zod/src/v4/core/json-schema-processors.ts`, line 853
- **Tool:** ESLINT  ·  **Rule:** `@typescript-eslint/no-explicit-any`
- **Message:** Unexpected any. Specify a different type.

```text
  845 |     // Registry case
  846 |     const registry = input as $ZodRegistry<{ id?: string | undefined }>;
  847 |     const ctx = initializeContext({ ...params, processors: allProcessors });
  848 |     const defs: any = {};
  849 | 
  850 |     // First pass: process all schemas to build the seen map
  851 |     for (const entry of registry._idmap.entries()) {
  852 |       const [_, schema] = entry;
> 853 |       processSchema(schema, ctx as any);
  854 |     }
  855 | 
  856 |     const schemas: Record<string, JSONSchema.BaseSchema> = {};
  857 |     const external = {
  858 |       registry,
  859 |       uri: (params as RegistryToJSONSchemaParams)?.uri,
  860 |       defs,
  861 |     };
```

---

## main-01-28

- **Project / case:** `pr-zod-6541`
- **File:** `packages/zod/src/v4/core/json-schema-processors.ts`, line 628
- **Tool:** ESLINT  ·  **Rule:** `@typescript-eslint/no-explicit-any`
- **Message:** Unexpected any. Specify a different type.

```text
  620 | 
  621 |   // For looseRecord with regex patterns, use patternProperties. This correctly represents "only validate keys matching the pattern" semantics and composes well with allOf (intersections)
  622 |   const keyType = def.keyType as schemas.$ZodTypes;
  623 |   const keyBag = keyType._zod.bag as schemas.$ZodStringInternals<unknown>["bag"] | undefined;
  624 |   const patterns = keyBag?.patterns;
  625 | 
  626 |   if (def.mode === "loose" && patterns && patterns.size > 0) {
  627 |     // Use patternProperties for looseRecord with regex patterns
> 628 |     const valueSchema = processSchema(def.valueType, ctx as any, {
  629 |       ...params,
  630 |       path: [...params.path, "patternProperties", "*"],
  631 |     });
  632 |     json.patternProperties = {};
  633 |     for (const pattern of patterns) {
  634 |       assignProp(json.patternProperties, exactPattern(pattern).source, valueSchema);
  635 |     }
  636 |   } else {
```

---

## main-01-29

- **Project / case:** `pr-zod-6541`
- **File:** `packages/zod/src/v4/core/json-schema-processors.ts`, line 417
- **Tool:** ESLINT  ·  **Rule:** `@typescript-eslint/no-explicit-any`
- **Message:** Unexpected any. Specify a different type.

```text
  409 |   }
  410 | 
  411 |   json.type = "object";
  412 |   json.properties = {};
  413 |   for (const key in def.shape) {
  414 |     assignProp(
  415 |       json.properties,
  416 |       key,
> 417 |       processSchema(def.shape[key]!, ctx as any, {
  418 |         ...params,
  419 |         path: [...params.path, "properties", key],
  420 |       })
  421 |     );
  422 |   }
  423 |   // input-side optionality in both modes: the parsed value is the input, so a defaulted key that stays absent must not be required of the output either
  424 |   const required = Object.keys(def.shape).filter((key) => inputOptin(def.shape[key]!) === undefined);
  425 |   if (required.length > 0) json.required = required;
```

---

## main-01-30

- **Project / case:** `pr-axios-11082`
- **File:** `tests/module/cjs/tests/helpers/cjs-added-types.ts`, line 35
- **Tool:** ESLINT  ·  **Rule:** `@typescript-eslint/no-unused-vars`
- **Message:** 'contentTooLargeStatus' is assigned a value but never used.

```text
  27 |   {}
  28 | );
  29 | const cancelFlag: boolean | undefined = cancel.__CANCEL__;
  30 | const cancelCtor: typeof axios.CanceledError = axios.Cancel;
  31 | const cancelFromAlias = new cancelCtor('from alias');
  32 | 
  33 | const status = axios.HttpStatusCode.WebServerIsDown;
  34 | const unknownErrorStatus = axios.HttpStatusCode.WebServerReturnsAnUnknownError;
> 35 | const contentTooLargeStatus = axios.HttpStatusCode.ContentTooLarge;
  36 | const unprocessableContentStatus = axios.HttpStatusCode.UnprocessableContent;
  37 | 
  38 | class CustomBlob {
  39 |   constructor(_parts?: any[]) {}
  40 | }
  41 | 
  42 | const serializerOptions: axios.FormSerializerOptions = {
  43 |   maxDepth: 2,
```
