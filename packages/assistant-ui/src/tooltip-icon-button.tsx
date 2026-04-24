"use client";

import { type ComponentPropsWithRef, forwardRef, type ReactElement } from "react";
import { cn } from "@gitintel/ui";

export type TooltipIconButtonProps = ComponentPropsWithRef<"button"> & {
  tooltip: string;
  side?: "top" | "bottom" | "left" | "right";
};

export const TooltipIconButton = forwardRef<
  HTMLButtonElement,
  TooltipIconButtonProps & { children?: ReactElement }
>(({ children, tooltip, side = "bottom", className, ...rest }, ref) => {
  return (
    <button
      ref={ref}
      className={cn(
        "relative inline-flex size-6 items-center justify-center rounded-md text-slate-400 transition-colors hover:bg-white/10 hover:text-white",
        className,
      )}
      title={tooltip}
      {...rest}
    >
      {children}
    </button>
  );
});

TooltipIconButton.displayName = "TooltipIconButton";
