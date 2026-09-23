"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

export type BreadcrumbItem = {
  label: string;
  href?: string;
};

export function Breadcrumb({ items }: { items: BreadcrumbItem[] }) {
  const pathname = usePathname();

  if (!items?.length) return null;

  let visible: BreadcrumbItem[];
  if (items.length > 5) {
    visible = [items[0], { label: "…" }, ...items.slice(-3)];
  } else {
    visible = items;
  }

  return (
    <nav className="breadcrumb" aria-label="Breadcrumb">
      <ol>
        {visible.map((item, i) => {
          const isLast = i === visible.length - 1;
          const isEllipsis = item.label === "…" && !item.href;

          if (isLast || !item.href) {
            return (
              <li key={`${pathname}-${i}`} aria-current={isLast ? "page" : undefined}>
                <span className="breadcrumb-current">{item.label}</span>
              </li>
            );
          }

          return (
            <li key={item.href}>
              <Link href={item.href}>{item.label}</Link>
              {!isEllipsis && <span className="breadcrumb-sep" aria-hidden="true">/</span>}
            </li>
          );
        })}
      </ol>
    </nav>
  );
}
