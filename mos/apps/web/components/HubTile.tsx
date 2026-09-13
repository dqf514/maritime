"use client";

import Link from "next/link";
import { ReactNode } from "react";
import { NavIcon, resolveIconId } from "@/components/NavIcon";

type HubTileProps = {
  href: string;
  title: string;
  description?: string;
  icon?: string;
  meta?: ReactNode;
  className?: string;
  style?: React.CSSProperties;
};

/** Icon + title hub link — whole tile is the affordance (no “Open →” footer). */
export function HubTile({ href, title, description, icon, meta, className = "", style }: HubTileProps) {
  const iconId = icon || resolveIconId(href);
  return (
    <Link href={href} className={`wb-tile wb-tile-icon ${className}`.trim()} style={style} title={title}>
      <span className="wb-tile-icon-mark" aria-hidden>
        <NavIcon id={iconId} size={26} />
      </span>
      <span className="wb-tile-body">
        <h3>{title}</h3>
        {description ? <p>{description}</p> : null}
        {meta ? <div className="wb-tile-meta">{meta}</div> : null}
      </span>
    </Link>
  );
}
