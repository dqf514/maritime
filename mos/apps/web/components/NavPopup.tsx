"use client";

// 弹出式菜单导航 — 左栏只放顶级分区，点击弹出分类菜单
// 多层内容分门别类展示，一次点击快速进入

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { NavIcon, sectionIconId } from "@/components/NavIcon";
import { useI18n } from "@/lib/i18n";

export type NavItem = { id: string; label: string; href: string; label_zh?: string };
export type NavSection = {
  section: string;
  label: string;
  items: NavItem[];
};

type Props = {
  sections: NavSection[];
  navCollapsed: boolean;
  pathname: string;
  onNavigate: () => void;
};

/** 将 items 按前缀自动分组（如 finance 下的 payment-batches/gl 归为"财务工具"） */
function autoGroupItems(items: NavItem[], section: string): { group: string; items: NavItem[] }[] {
  if (items.length <= 6) return [{ group: "", items }];

  // 按 href 路径前缀分组
  const groups = new Map<string, NavItem[]>();
  for (const item of items) {
    const parts = item.href.replace(/^\//, "").split("/");
    const group = parts.length > 1 ? parts[0] : section;
    if (!groups.has(group)) groups.set(group, []);
    groups.get(group)!.push(item);
  }

  // 如果分组结果是单组（全部同一前缀），按功能语义手动分组
  if (groups.size <= 1) {
    return semanticGroup(items, section);
  }

  return [...groups.entries()].map(([group, items]) => ({ group, items }));
}

/** 语义分组 — 当路径无法区分时 */
function semanticGroup(items: NavItem[], section: string): { group: string; items: NavItem[] }[] {
  // Finance section: 桌面 / 支付 / 总账 / 工具
  if (section.includes("finance") || section.includes("Finance")) {
    const desk = items.filter((i) => ["finance", "laytimes", "claims", "invoices", "pnl"].some((k) => i.id.includes(k)));
    const payments = items.filter((i) => i.id.includes("payment") || i.id.includes("bank"));
    const gl = items.filter((i) => i.id.includes("gl") || i.id.includes("journal") || i.id.includes("account"));
    const tools = items.filter((i) => !desk.includes(i) && !payments.includes(i) && !gl.includes(i));
    const result = [];
    if (desk.length) result.push({ group: "Desk", items: desk });
    if (payments.length) result.push({ group: "Payments", items: payments });
    if (gl.length) result.push({ group: "GL", items: gl });
    if (tools.length) result.push({ group: "", items: tools });
    return result;
  }

  // Operations: 航次 / 调度 / 其他
  if (section.includes("operation") || section.includes("Operation")) {
    const voyages = items.filter((i) => i.id.includes("voyage") || i.id.includes("ops") || i.id.includes("noon"));
    const scheduling = items.filter((i) => i.id.includes("schedule") || i.id.includes("cargo") || i.id.includes("berth"));
    const other = items.filter((i) => !voyages.includes(i) && !scheduling.includes(i));
    const result = [];
    if (voyages.length) result.push({ group: "Voyages", items: voyages });
    if (scheduling.length) result.push({ group: "Scheduling", items: scheduling });
    if (other.length) result.push({ group: "", items: other });
    return result;
  }

  // 默认：单组
  return [{ group: "", items }];
}

export function NavPopup({ sections, navCollapsed, pathname, onNavigate }: Props) {
  const { t } = useI18n();
  const [openSection, setOpenSection] = useState<string | null>(null);
  const [popupPos, setPopupPos] = useState<{ top: number; left: number }>({ top: 0, left: 0 });
  const popupRef = useRef<HTMLDivElement>(null);
  const btnRefs = useRef<Map<string, HTMLButtonElement>>(new Map());

  const isActive = useCallback(
    (href: string) => {
      const p = (pathname || "/").split("?")[0];
      return p === href || p.startsWith(href + "/");
    },
    [pathname],
  );

  // 点击外部关闭
  useEffect(() => {
    if (!openSection) return;
    function onDoc(e: MouseEvent) {
      if (popupRef.current?.contains(e.target as Node)) return;
      const btn = btnRefs.current.get(openSection!);
      if (btn?.contains(e.target as Node)) return;
      setOpenSection(null);
    }
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [openSection]);

  // ESC 关闭
  useEffect(() => {
    if (!openSection) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") setOpenSection(null);
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [openSection]);

  function toggleSection(sec: string, e: React.MouseEvent<HTMLButtonElement>) {
    if (openSection === sec) {
      setOpenSection(null);
      return;
    }
    const btn = e.currentTarget;
    const rect = btn.getBoundingClientRect();
    setPopupPos({
      top: rect.top,
      left: navCollapsed ? rect.right + 2 : rect.right + 2,
    });
    setOpenSection(sec);
  }

  return (
    <>
      <div className="nav-popup-items">
        {sections.map((sec) => {
          const secLabel = t(`section.${sec.section}`, sec.label);
          const isOpen = openSection === sec.section;
          const hasActive = sec.items.some((item) => isActive(item.href));
          return (
            <button
              key={sec.section}
              ref={(el) => {
                if (el) btnRefs.current.set(sec.section, el);
              }}
              type="button"
              className={`nav-popup-btn ${isOpen ? "open" : ""} ${hasActive ? "has-active" : ""}`}
              onClick={(e) => toggleSection(sec.section, e)}
              title={secLabel}
              aria-expanded={isOpen}
            >
              <span className="nav-section-icon" aria-hidden>
                <NavIcon id={sectionIconId(sec.section)} />
              </span>
              {!navCollapsed && <span className="nav-section-text">{secLabel}</span>}
              {!navCollapsed && <em className="nav-popup-arrow" aria-hidden>▸</em>}
            </button>
          );
        })}
      </div>

      {/* 弹出菜单 */}
      {openSection ? (
        <div
          ref={popupRef}
          className="nav-popup-menu"
          style={{ top: popupPos.top, left: popupPos.left }}
        >
          {(() => {
            const sec = sections.find((s) => s.section === openSection);
            if (!sec) return null;
            const secLabel = t(`section.${sec.section}`, sec.label);
            const groups = autoGroupItems(sec.items, sec.section);

            return (
              <>
                <div className="nav-popup-header">
                  <NavIcon id={sectionIconId(sec.section)} />
                  <strong>{secLabel}</strong>
                  <span className="nav-popup-count">{sec.items.length}</span>
                </div>
                <div className="nav-popup-body">
                  {groups.map((g, gi) => (
                    <div key={gi} className="nav-popup-group">
                      {g.group ? (
                        <div className="nav-popup-group-label">{g.group}</div>
                      ) : null}
                      {g.items.map((item) => {
                        const label = t(`nav.${item.id}`, item.label);
                        return (
                          <Link
                            key={item.href}
                            href={item.href}
                            className={`nav-popup-item ${isActive(item.href) ? "active" : ""}`}
                            onClick={() => {
                              setOpenSection(null);
                              onNavigate();
                            }}
                          >
                            <NavIcon id={item.id} />
                            <span>{label}</span>
                          </Link>
                        );
                      })}
                    </div>
                  ))}
                </div>
              </>
            );
          })()}
        </div>
      ) : null}
    </>
  );
}
