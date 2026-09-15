"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { apiGet, apiPost, type OnboardingState } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

const VISIBLE_ITEMS = 5;

export function OnboardingCard() {
  const { t, locale } = useI18n();
  const [state, setState] = useState<OnboardingState | null>(null);
  const [hidden, setHidden] = useState(false);
  const [confirmDismiss, setConfirmDismiss] = useState(false);

  const isZh = locale.startsWith("zh");
  const pick = (v?: { en: string; zh?: string }) => (v ? (isZh ? v.zh || v.en : v.en) : "");

  useEffect(() => {
    apiGet("/api/v1/onboarding")
      .then((data) => setState(data))
      .catch(() => undefined);
  }, []);

  if (hidden || !state || state.dismissed) return null;
  const { done, total } = state.progress;
  if (total > 0 && done >= total) return null;

  const items = state.items.slice(0, VISIBLE_ITEMS);
  const remaining = state.items.length - items.length;
  const pct = total > 0 ? Math.round((done / total) * 100) : 0;

  async function dismiss() {
    setConfirmDismiss(false);
    setHidden(true);
    try {
      await apiPost("/api/v1/onboarding/dismiss");
    } catch {
      setHidden(true);
    }
  }

  return (
    <div className="panel onboard-card">
      <div className="onboard-head">
        <h2 style={{ margin: 0 }}>{t("onboarding.title", "快速上手")}</h2>
        <button type="button" className="btn btn-ghost btn-sm" onClick={() => setConfirmDismiss(true)}>
          {t("onboarding.dismiss", "不再显示")}
        </button>
      </div>
      <div
        className="onboard-progress"
        role="progressbar"
        aria-valuenow={done}
        aria-valuemin={0}
        aria-valuemax={total}
        aria-label={t("onboarding.progress", "上手进度 {done}/{total}", { done, total })}
      >
        <span style={{ width: `${pct}%` }} />
      </div>
      <div className="onboard-list">
        {items.map((item) =>
          item.done ? (
            <div key={item.key} className="onboard-item done">
              <span className="onboard-check" aria-hidden>
                ✓
              </span>
              <span className="onboard-item-main">
                <span className="onboard-label">{pick(item.label)}</span>
              </span>
            </div>
          ) : (
            <Link key={item.key} href={item.href || "/home"} className="onboard-item">
              <span className="onboard-check" aria-hidden />
              <span className="onboard-item-main">
                <span className="onboard-label">{pick(item.label)}</span>
                {pick(item.hint) ? <small className="onboard-hint">{pick(item.hint)}</small> : null}
              </span>
            </Link>
          ),
        )}
      </div>
      {remaining > 0 ? (
        <p className="onboard-more">{t("onboarding.more", "还有 {n} 项", { n: remaining })}</p>
      ) : null}
      <ConfirmDialog
        open={confirmDismiss}
        title={t("common.confirm", "确认操作")}
        message={t("onboarding.confirm_dismiss", "不再显示新手引导？之后可在系统设置中重置。")}
        onConfirm={dismiss}
        onCancel={() => setConfirmDismiss(false)}
      />
    </div>
  );
}
