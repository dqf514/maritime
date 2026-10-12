"use client";

// D2 时间单元：港口/指定时区本地时间 + GMT±N 标签，hover 显示全精度 ISO（D1）。
// 用法：<PortTime value={pc.eta} tz={port?.timezone} />

import { fullTimestamp, formatInTz, tzShort } from "@/lib/datetime";

type Props = {
  value: string | number | Date | null | undefined;
  /** IANA 时区（如 "Asia/Shanghai"）；缺省按 UTC */
  tz?: string | null;
  /** 是否追加 GMT±N 标签 */
  showTz?: boolean;
  className?: string;
};

export function PortTime({ value, tz, showTz = true, className }: Props) {
  if (value == null || value === "") return <span className={className}>—</span>;
  const label = showTz ? tzShort(tz) : "";
  return (
    <span className={`port-time${className ? ` ${className}` : ""}`} title={fullTimestamp(value, tz)}>
      {formatInTz(value, tz)}
      {label ? <span className="port-time-tz">{label}</span> : null}
    </span>
  );
}
