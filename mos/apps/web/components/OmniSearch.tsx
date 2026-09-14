"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { apiCreateBackup, apiRunSelfCheck, apiSearch, type SearchHit } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

export function OmniSearch() {
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<SearchHit[]>([]);
  const [active, setActive] = useState(0);
  const [flash, setFlash] = useState("");
  const router = useRouter();
  const { t } = useI18n();

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setOpen(true);
      }
      if (e.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    const handle = setTimeout(() => {
      apiSearch(q)
        .then((data) => {
          if (!cancelled) {
            setHits(data);
            setActive(0);
          }
        })
        .catch(() => setHits([]));
    }, 200);
    return () => {
      cancelled = true;
      clearTimeout(handle);
    };
  }, [q, open]);

  useEffect(() => {
    if (!flash) return;
    const handle = setTimeout(() => setFlash(""), 3000);
    return () => clearTimeout(handle);
  }, [flash]);

  const go = async (hit: SearchHit) => {
    setOpen(false);
    setQ("");
    try {
      if (hit.action === "selfcheck.run") {
        await apiRunSelfCheck();
        setFlash(t("omni.selfcheck_ok", "SelfCheck started"));
        if (hit.href) router.push(hit.href);
        return;
      }
      if (hit.action === "dataops.backup") {
        await apiCreateBackup();
        setFlash(t("omni.backup_ok", "Backup created"));
        if (hit.href) router.push(hit.href);
        return;
      }
      if (hit.href) router.push(hit.href);
    } catch (e: any) {
      setFlash(e?.message || t("common.failed", "Failed"));
    }
  };

  return (
    <>
      <button type="button" className="search-btn" onClick={() => setOpen(true)}>
        <span className="search-label-full">{t("omni.button", "Search…  Ctrl+K")}</span>
        <span className="search-label-short" aria-hidden>
          {t("omni.button_short", "搜索")}
        </span>
      </button>
      {flash ? (
        <span className="muted" style={{ fontSize: "0.75rem", marginLeft: "0.35rem" }} title={flash}>
          {flash}
        </span>
      ) : null}
      {open ? (
        <div className="palette-backdrop" onClick={() => setOpen(false)}>
          <div className="palette" onClick={(e) => e.stopPropagation()}>
            <input
              autoFocus
              placeholder={t("omni.placeholder", "Type a command, page, or keyword…")}
              value={q}
              onChange={(e) => setQ(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "ArrowDown") {
                  e.preventDefault();
                  setActive((i) => Math.min(i + 1, Math.max(hits.length - 1, 0)));
                }
                if (e.key === "ArrowUp") {
                  e.preventDefault();
                  setActive((i) => Math.max(i - 1, 0));
                }
                if (e.key === "Enter" && hits[active]) go(hits[active]).catch(() => undefined);
              }}
            />
            <ul>
              {hits.map((hit, idx) => (
                <li
                  key={hit.id}
                  className={idx === active ? "active" : ""}
                  onMouseEnter={() => setActive(idx)}
                  onClick={() => go(hit).catch(() => undefined)}
                >
                  <span>{hit.title}</span>
                  <span className="meta">{hit.module}{hit.action ? ` · ${hit.action}` : ""}</span>
                </li>
              ))}
              {!hits.length ? <li className="meta">{t("omni.empty", "No matches")}</li> : null}
            </ul>
          </div>
        </div>
      ) : null}
    </>
  );
}
