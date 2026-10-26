"use client";

import { PointerEvent, useEffect, useRef, useState } from "react";
import { useFocusTrap } from "@/components/useFocusTrap";
import { useI18n } from "@/lib/i18n";

export type CropKind = "logo" | "company_logo" | "icon" | "favicon";

const SPECS: Record<CropKind, { ratio: number; outW: number; outH: number }> = {
  // 产品门户 logo 是横版字标（登录/门户页宽条展示）
  logo: { ratio: 3, outW: 600, outH: 200 },
  // 租户公司 logo 展示在壳层左上角的正方形槽位（28×28）与单据信头 —— 1:1
  company_logo: { ratio: 1, outW: 512, outH: 512 },
  icon: { ratio: 1, outW: 512, outH: 512 },
  favicon: { ratio: 1, outW: 64, outH: 64 },
};

/** 默认选区宽度（= 上限；只能缩小、不能超过，避免图片盖不住选区） */
function defaultFrameW(kind: CropKind) {
  return SPECS[kind].ratio >= 3 ? 420 : 280;
}
/** 选区最小宽度 — 允许缩小选区（用户反馈：无法缩小选区） */
function minFrameW(kind: CropKind) {
  return SPECS[kind].ratio >= 3 ? 160 : 120;
}

type Props = {
  open: boolean;
  kind: CropKind;
  file: File | null;
  busy?: boolean;
  error?: string;
  onCancel: () => void;
  onConfirm: (blob: Blob) => void | Promise<void>;
};

function clampPan(x: number, y: number, scale: number, imgW: number, imgH: number, boxW: number, boxH: number) {
  const minX = Math.min(0, boxW - imgW * scale);
  const minY = Math.min(0, boxH - imgH * scale);
  return { x: Math.min(0, Math.max(minX, x)), y: Math.min(0, Math.max(minY, y)) };
}

/** 定比裁剪：可缩小选区、拖动平移、滑块缩放，导出定尺寸 PNG。 */
export function ImageCropModal({ open, kind, file, busy, error, onCancel, onConfirm }: Props) {
  const { t } = useI18n();
  const spec = SPECS[kind];
  // 模态对话框：焦点陷阱 + 关闭后焦点归还
  const { ref: modalRef, onKeyDown: trapKeyDown } = useFocusTrap<HTMLDivElement>(open);
  const [frameW, setFrameW] = useState(() => defaultFrameW(kind));
  const boxW = frameW;
  const boxH = Math.round(frameW / spec.ratio);

  const [img, setImg] = useState<HTMLImageElement | null>(null);
  const [imgUrl, setImgUrl] = useState("");
  // base = 默认选区下的 cover 缩放：图片尺度与选区尺寸解耦，
  // 缩小选区 → 真正缩小所选区域（而不是把图片一起缩小）。
  const [base, setBase] = useState(1);
  const [zoom, setZoom] = useState(1);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const [exportErr, setExportErr] = useState("");
  const dragRef = useRef<{ startX: number; startY: number; panX: number; panY: number } | null>(null);

  useEffect(() => {
    if (!open || !file) return;
    const url = URL.createObjectURL(file);
    setImgUrl(url);
    setImg(null);
    setExportErr("");
    const w0 = defaultFrameW(kind);
    const h0 = Math.round(w0 / SPECS[kind].ratio);
    setFrameW(w0);
    const el = new Image();
    el.onload = () => {
      const cover = Math.max(w0 / el.naturalWidth, h0 / el.naturalHeight);
      setBase(cover);
      setZoom(1);
      setPan({ x: (w0 - el.naturalWidth * cover) / 2, y: (h0 - el.naturalHeight * cover) / 2 });
      setImg(el);
    };
    el.onerror = () => setExportErr(t("crop.load_fail", "图片读取失败，请换一张"));
    el.src = url;
    return () => {
      URL.revokeObjectURL(url);
      setImg(null);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, file, kind]);

  // 选区尺寸变化后重新夹紧平移，保证图片始终盖住选区
  useEffect(() => {
    if (!img) return;
    setPan((p) => clampPan(p.x, p.y, base * zoom, img.naturalWidth, img.naturalHeight, boxW, boxH));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [boxW, boxH]);

  useEffect(() => {
    if (!open) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onCancel();
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, onCancel]);

  if (!open) return null;

  const scale = base * zoom;

  function applyZoom(v: number) {
    setZoom(v);
    if (!img) return;
    setPan((p) => clampPan(p.x, p.y, base * v, img.naturalWidth, img.naturalHeight, boxW, boxH));
  }

  function onPointerDown(e: PointerEvent<HTMLDivElement>) {
    if (!img) return;
    e.currentTarget.setPointerCapture(e.pointerId);
    dragRef.current = { startX: e.clientX, startY: e.clientY, panX: pan.x, panY: pan.y };
  }

  function onPointerMove(e: PointerEvent<HTMLDivElement>) {
    const d = dragRef.current;
    if (!d || !img) return;
    setPan(clampPan(d.panX + e.clientX - d.startX, d.panY + e.clientY - d.startY, scale, img.naturalWidth, img.naturalHeight, boxW, boxH));
  }

  function onPointerUp() {
    dragRef.current = null;
  }

  async function confirm() {
    if (!img) return;
    setExportErr("");
    try {
      const sx = -pan.x / scale;
      const sy = -pan.y / scale;
      const sw = boxW / scale;
      const sh = boxH / scale;
      const canvas = document.createElement("canvas");
      canvas.width = spec.outW;
      canvas.height = spec.outH;
      const ctx = canvas.getContext("2d");
      if (!ctx) throw new Error("canvas 2d unsupported");
      ctx.drawImage(img, sx, sy, sw, sh, 0, 0, spec.outW, spec.outH);
      const blob = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, "image/png"));
      if (!blob) throw new Error("toBlob failed");
      await onConfirm(blob);
    } catch (err: any) {
      setExportErr(t("crop.export_fail", "导出失败：{err}", { err: String(err?.message || err) }));
    }
  }

  const kindLabel = t(`page.branding.${kind}`, kind);
  const shownErr = exportErr || error || "";

  return (
    <div className="record-modal-backdrop" role="presentation" onClick={onCancel}>
      <div
        className="record-modal"
        role="dialog"
        aria-modal="true"
        aria-label={t("crop.title", "裁剪 {kind}", { kind: kindLabel })}
        ref={modalRef}
        onKeyDown={trapKeyDown}
        onClick={(e) => e.stopPropagation()}
      >
        <header className="record-modal-head">
          <h2>{t("crop.title", "裁剪 {kind}", { kind: kindLabel })}</h2>
          <button type="button" className="icon-btn record-modal-x" onClick={onCancel} aria-label={t("common.close", "关闭")}>
            ×
          </button>
        </header>
        <div className="record-modal-body">
          <div
            className="crop-box"
            style={{ width: boxW, height: boxH, maxWidth: "100%" }}
            onPointerDown={onPointerDown}
            onPointerMove={onPointerMove}
            onPointerUp={onPointerUp}
            onPointerCancel={onPointerUp}
          >
            {img ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img
                src={imgUrl}
                alt=""
                draggable={false}
                style={{
                  position: "absolute",
                  left: 0,
                  top: 0,
                  maxWidth: "none",
                  transform: `translate(${pan.x}px, ${pan.y}px) scale(${scale})`,
                  transformOrigin: "0 0",
                  userSelect: "none",
                }}
              />
            ) : (
              <p className="muted" style={{ margin: "auto" }}>
                {t("common.loading", "加载中…")}
              </p>
            )}
          </div>
          <div className="crop-controls">
            <label className="crop-control">
              <span className="crop-control-label">
                {t("crop.frame", "选区大小")} <span className="crop-control-val">{boxW} × {boxH}</span>
              </span>
              <input
                type="range"
                min={minFrameW(kind)}
                max={defaultFrameW(kind)}
                step={2}
                value={frameW}
                onChange={(e) => setFrameW(Number(e.target.value))}
                disabled={!img}
              />
            </label>
            <label className="crop-control">
              <span className="crop-control-label">
                {t("crop.zoom", "缩放")} <span className="crop-control-val">×{zoom.toFixed(2)}</span>
              </span>
              <input
                type="range"
                min={1}
                max={8}
                step={0.01}
                value={zoom}
                onChange={(e) => applyZoom(Number(e.target.value))}
                disabled={!img}
              />
            </label>
          </div>
          <p className="crop-out">
            {t("crop.output", "输出尺寸")} <strong>{spec.outW} × {spec.outH} px</strong> · PNG · {kindLabel}
          </p>
          <p className="muted crop-hint">
            {t("crop.hint2", "拖动调整位置，滑块缩放，选区可缩小；输出为固定尺寸 PNG。")}
          </p>
          {shownErr ? <p className="flash-err">{shownErr}</p> : null}
          <footer className="record-modal-foot">
            <span />
            <div className="record-modal-actions">
              <button type="button" className="btn btn-ghost" onClick={onCancel} disabled={busy}>
                {t("common.cancel", "取消")}
              </button>
              <button type="button" className="btn btn-primary" onClick={confirm} disabled={busy || !img}>
                {busy ? "…" : t("crop.confirm", "确认上传")}
              </button>
            </div>
          </footer>
        </div>
      </div>
    </div>
  );
}
