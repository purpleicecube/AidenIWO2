// Ambient module declaration for `pdf-parse/lib/pdf-parse.js`.
//
// The default pdf-parse package exports types only for the main entry.
// server/text-extractor.ts deliberately imports the lib file directly to
// bypass pdf-parse's index.js test-harness bug. Declaring the module as
// untyped here is enough for tsc — the runtime code already casts to
// `any` before invocation.

declare module "pdf-parse/lib/pdf-parse.js";
