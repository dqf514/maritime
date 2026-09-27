"use client";

// U6 保存视图：把当前 URL 查询（tab/filter/page）存为命名视图，一键切换。
// v1 存 localStorage（按浏览器）；后端持久化与跨设备同步留待 U6-v2。

import { useEffect, useState } from "react";
import { useI18n } from "@/lib/i18n";

type SavedView = { name: string; query: string; savedAt: string };

function loadViews(lsKey: string): SavedView[] {
  try {
    const raw = JSON.parse(localStorage.getItem(lsKey) || "[]");
    return Array.isArray(raw) ? raw : [];
  } catch {
    return [];
  }
}

export function SavedViews({ storageKey, onApply }: { storageKey: string; onApply: (query: string) => void }) {
  const { t } = useI18n();
  const lsKey = `marios_views_${storageKey}`;
  const [views, setViews] = useState<SavedView[]>([]);
  const [name, setName] = useState("");

  useEffect(() => {
    setViews(loadViews(lsKey));
  }, [lsKey]);

  function persist(next: SavedView[]) {
    setViews(next);
    try {
      localStorage.setItem(lsKey, JSON.stringify(next));
    } catch {
      // 存储满/隐私模式：仅内存态
    }
  }

  function save() {
    const n = name.trim();
    if (!n) return;
    persist([...views.filter((v) => v.name !== n), { name: n, query: window.location.search, savedAt: new Date().toISOString() }]);
    setName("");
  }

  function remove(viewName: string) {
    persist(views.filter((v) => v.name !== viewName));
  }

  return (
    <div className="saved-views">
      <select
        className="saved-views-select"
        value=""
        onChange={(e) => {
          const v = views.find((x) => x.name === e.target.value);
          if (v) onApply(v.query);
        }}
        aria-label={t("views.label", "保存的视图")}
      >
        <option value="">{t("views.label", "保存的视图")}…</option>
        {views.map((v) => (
          <option key={v.name} value={v.name}>
            {v.name}
          </option>
        ))}
      </select>
      <input
        className="saved-views-name"
        value={name}
        onChange={(e) => setName(e.target.value)}
        placeholder={t("views.name_placeholder", "视图名称")}
        onKeyDown={(e) => {
          if (e.key === "Enter") {
            e.preventDefault();
            save();
          }
        }}
      />
      <button type="button" className="btn btn-sm btn-ghost" onClick={save} disabled={!name.trim()}>
        {t("views.save", "保存当前")}
      </button>
      {views.length ? (
        <button
          type="button"
          className="btn btn-sm btn-ghost"
          onClick={() => {
            const last = views[views.length - 1];
            if (last) remove(last.name);
          }}
          title={t("views.delete_last", "删除最近保存的视图")}
        >
          ×
        </button>
      ) : null}
    </div>
  );
}
