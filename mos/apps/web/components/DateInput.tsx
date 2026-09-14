"use client";

import { useRef, type CSSProperties } from "react";
import { useI18n } from "@/lib/i18n";

type CommonProps = {
  value: string;
  onChange: (value: string) => void;
  required?: boolean;
  disabled?: boolean;
  className?: string;
  id?: string;
  name?: string;
  style?: CSSProperties;
};

function openNativePicker(el: HTMLInputElement | null, disabled?: boolean) {
  if (!el || disabled) return;
  try {
    el.showPicker?.();
  } catch {
    el.click();
  }
}

function normalizeDate(raw: string): string {
  const v = raw.trim().replace(/[/.]/g, "-");
  const m = /^(\d{4})-(\d{1,2})-(\d{1,2})$/.exec(v);
  if (!m) return raw.trim();
  return `${m[1]}-${m[2].padStart(2, "0")}-${m[3].padStart(2, "0")}`;
}

function normalizeDateTime(raw: string): string {
  const v = raw.trim().replace(" ", "T").replace(/[/.]/g, "-");
  const m = /^(\d{4})-(\d{1,2})-(\d{1,2})T(\d{1,2}):(\d{2})(?::(\d{2}))?$/.exec(v);
  if (!m) return raw.trim();
  return `${m[1]}-${m[2].padStart(2, "0")}-${m[3].padStart(2, "0")}T${m[4].padStart(2, "0")}:${m[5]}`;
}

/** App-locale date field — avoids OS Chinese native date chrome when UI is English. */
export function DateInput({ value, onChange, required, disabled, className, id, name, style }: CommonProps) {
  const { locale, t } = useI18n();
  const pickerRef = useRef<HTMLInputElement>(null);
  const lang = locale.startsWith("zh") ? "zh-CN" : "en-US";
  const valid = /^\d{4}-\d{2}-\d{2}$/.test(value || "");

  return (
    <div className={`locale-date-field ${className || ""}`} style={style} lang={lang}>
      <input
        type="text"
        id={id}
        name={name}
        lang={lang}
        inputMode="numeric"
        autoComplete="off"
        spellCheck={false}
        placeholder="YYYY-MM-DD"
        value={value || ""}
        required={required}
        disabled={disabled}
        pattern="\d{4}-\d{2}-\d{2}"
        title={t("common.date_format", "Format: YYYY-MM-DD")}
        onChange={(e) => onChange(e.target.value)}
        onBlur={(e) => {
          const next = normalizeDate(e.target.value);
          if (next !== e.target.value) onChange(next);
        }}
      />
      <input
        ref={pickerRef}
        type="date"
        lang={lang}
        className="locale-date-native"
        value={valid ? value : ""}
        disabled={disabled}
        tabIndex={-1}
        aria-hidden
        onChange={(e) => onChange(e.target.value)}
      />
      <button
        type="button"
        className="locale-date-trigger"
        disabled={disabled}
        aria-label={t("common.pick_date", "Pick date")}
        onClick={() => openNativePicker(pickerRef.current, disabled)}
      >
        <svg viewBox="0 0 20 20" width="15" height="15" aria-hidden>
          <path
            fill="currentColor"
            d="M6 2a1 1 0 0 1 1 1v1h6V3a1 1 0 1 1 2 0v1h1a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h1V3a1 1 0 0 1 1-1zm10 7H4v7h12V9zM4 7h12V6H4v1z"
          />
        </svg>
      </button>
    </div>
  );
}

/** App-locale datetime field — stores HTML datetime-local value (YYYY-MM-DDTHH:mm). */
export function DateTimeInput({ value, onChange, required, disabled, className, id, name, style }: CommonProps) {
  const { locale, t } = useI18n();
  const pickerRef = useRef<HTMLInputElement>(null);
  const lang = locale.startsWith("zh") ? "zh-CN" : "en-US";
  const valid = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}/.test(value || "");

  return (
    <div className={`locale-date-field ${className || ""}`} style={style} lang={lang}>
      <input
        type="text"
        id={id}
        name={name}
        lang={lang}
        inputMode="numeric"
        autoComplete="off"
        spellCheck={false}
        placeholder="YYYY-MM-DDTHH:mm"
        value={value || ""}
        required={required}
        disabled={disabled}
        pattern="\d{4}-\d{2}-\d{2}T\d{2}:\d{2}"
        title={t("common.datetime_format", "Format: YYYY-MM-DDTHH:mm")}
        onChange={(e) => onChange(e.target.value)}
        onBlur={(e) => {
          const next = normalizeDateTime(e.target.value);
          if (next !== e.target.value) onChange(next);
        }}
      />
      <input
        ref={pickerRef}
        type="datetime-local"
        lang={lang}
        className="locale-date-native"
        value={valid ? value.slice(0, 16) : ""}
        disabled={disabled}
        tabIndex={-1}
        aria-hidden
        onChange={(e) => onChange(e.target.value)}
      />
      <button
        type="button"
        className="locale-date-trigger"
        disabled={disabled}
        aria-label={t("common.pick_datetime", "Pick date & time")}
        onClick={() => openNativePicker(pickerRef.current, disabled)}
      >
        <svg viewBox="0 0 20 20" width="15" height="15" aria-hidden>
          <path
            fill="currentColor"
            d="M6 2a1 1 0 0 1 1 1v1h6V3a1 1 0 1 1 2 0v1h1a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h1V3a1 1 0 0 1 1-1zm10 7H4v7h12V9zM4 7h12V6H4v1z"
          />
        </svg>
      </button>
    </div>
  );
}
