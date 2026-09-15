"use client";

import { PointerEvent, useEffect, useRef, useState } from "react";
import { useI18n } from "@/lib/i18n";

export type CropKind = "logo" | "icon" | "favicon";

const SPECS: Record<CropKind, { ratio: number; outW: number; outH: number }> = {
  logo: { ratio: 3, outW: 600, outH: 200 },
  icon: { ratio: 1, outW: 512, outH: 512 },
  favicon: { ratio: 1, outW: 64, outH: 64 },
};

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

/** Fixed-ratio crop dialog: drag to pan, slider to zoom, exports PNG via offscreen canvas. */
export function ImageCropModal({ open, kind, file, busy, error, onCancel, onConfirm }: Props) {
  const { t } = useI18n();
  const spec = SPECS[kind];
  const boxW = spec.ratio >= 3 ? 420 : 280;
  const boxH = Math.round(boxW / spec.ratio);

  const [img, setImg] = useState<HTMLImageElement | null>(null);
  const [imgUrl, setImgUrl] = useState("");
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
    const el = new Image();
    el.onload = () => {
      const cover = Math.max(boxW / el.naturalWidth, boxH / el.naturalHeight);
      setBase(cover);
      setZoom(1);
      setPan({ x: (boxW - el.naturalWidth * cover) / 2, y: (boxH - el.naturalHeight * cover) / 2 });
      setImg(el);
    };
    el.onerror = () => setExportErr(t("crop.load_fail", "图片读取失败，请换一张"));
    el.src = url;
    return () => {
      URL.revokeObjectURL(url);
      setImg(null);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, file]);

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
          <label style={{ display: "block", marginTop: "0.75rem" }}>
            {t("crop.zoom", "缩放")}
            <input
              type="range"
              min={1}
              max={8}
              step={0.01}
              value={zoom}
              onChange={(e) => applyZoom(Number(e.target.value))}
              style={{ width: "100%" }}
              disabled={!img}
            />
          </label>
          <p className="muted" style={{ margin: "0.25rem 0 0" }}>
            {t("crop.hint", "拖动调整位置，滑块缩放。输出 {w}×{h} PNG。", { w: spec.outW, h: spec.outH })}
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
