// U9 表单默认值记忆：按表单键记住上次提交值，下次打开预填（ERP「上次值」行为）。

export function readFormDefaults<T extends Record<string, string>>(key: string, fallback: T): T {
  if (typeof window === "undefined") return fallback;
  try {
    const raw = JSON.parse(localStorage.getItem(`marios_form_${key}`) || "{}");
    return { ...fallback, ...raw };
  } catch {
    return fallback;
  }
}

export function writeFormDefaults(key: string, values: Record<string, string>) {
  if (typeof window === "undefined") return;
  try {
    localStorage.setItem(`marios_form_${key}`, JSON.stringify(values));
  } catch {
    // 忽略存储失败
  }
}
