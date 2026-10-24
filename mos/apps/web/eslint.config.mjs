import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";

const eslintConfig = defineConfig([
  ...nextVitals,
  ...nextTs,
  // 存量代码尚未按 core-web-vitals / typescript-eslint 严格规则改造，
  // 以下规则先降级为 warn（不阻塞 CI），后续按报告清单逐步清理。
  {
    rules: {
      "@typescript-eslint/no-explicit-any": "warn",
      "react-hooks/set-state-in-effect": "warn",
      "react-hooks/static-components": "warn",
      "react-hooks/immutability": "warn",
      "@next/next/no-img-element": "warn",
      "@next/next/no-location-assign-relative-destination": "warn",
    },
  },
  // 构建产物目录一律不参与 lint（.next-a11y-check 是 a11y 自检脚本的临时产物）
  globalIgnores([".next/**", ".next-*/**", "out/**", "build/**", "next-env.d.ts"]),
]);

export default eslintConfig;
