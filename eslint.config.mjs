import next from "eslint-config-next";
import prettier from "eslint-config-prettier";

// eslint-config-next v16 ships a native flat config (array), so we spread it
// directly instead of loading it through the legacy FlatCompat shim.
const eslintConfig = [
  {
    ignores: ["out/**", ".next/**", "node_modules/**", "src-tauri/**", "sidecar/**"],
  },
  ...next,
  prettier,
];

export default eslintConfig;
