// Resolves the "@/" path alias (tsconfig.json) for the compiled tests, via Node's public
// synchronous module hooks (they apply to require() in the CommonJS test build).
import path from "node:path";
import { registerHooks } from "node:module";

const src = path.join(import.meta.dirname, "..", ".test-build", "src");

registerHooks({
  resolve(specifier, context, nextResolve) {
    if (specifier.startsWith("@/")) return nextResolve(path.join(src, specifier.slice(2)), context);
    return nextResolve(specifier, context);
  },
});
