"use client";

import {
  type ComponentPropsWithRef,
  type ReactElement,
} from "react";
import { cn } from "@gitintel/ui";

export type TooltipIconButtonProps = ComponentPropsWithRef<"button"> & {
  tooltip: string;
  side?: "top" | "bottom" | "left" | "right";
};

export const TooltipIconButton = ({
  children,
  tooltip,
  side = "bottom",
  className,
  ...rest
}: TooltipIconButtonProps & { children?: ReactElement }) => {
  return (
    <button
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
};
