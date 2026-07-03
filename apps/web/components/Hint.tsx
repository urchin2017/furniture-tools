import type { ReactNode } from "react";

/**
 * 悬停显示的说明浮层（tooltip）。默认渲染一个 ⓘ 触发点；
 * 传 children 时以 children 作为触发元素（如整张卡片/标题），悬停即弹出 text。
 * 纯 CSS（group-hover），可用于 Server Component。
 */
export default function Hint({
  text,
  children,
  side = "bottom",
  className = "inline-flex",
}: {
  text: string;
  children?: ReactNode;
  side?: "bottom" | "right";
  className?: string;
}) {
  const pos =
    side === "right"
      ? "left-full top-0 ml-2"
      : "left-0 top-full mt-1.5";
  return (
    <span className={`relative group/hint ${className}`}>
      {children ?? (
        <span
          aria-hidden
          className="flex h-4 w-4 shrink-0 cursor-help items-center justify-center rounded-full border border-border text-[10px] leading-none text-muted"
        >
          ⓘ
        </span>
      )}
      <span
        role="tooltip"
        className={`pointer-events-none absolute ${pos} z-30 hidden w-max max-w-xs whitespace-normal rounded-lg border border-border bg-surface px-3 py-2 text-left text-xs font-normal leading-relaxed text-muted shadow-lg group-hover/hint:block`}
      >
        {text}
      </span>
    </span>
  );
}
