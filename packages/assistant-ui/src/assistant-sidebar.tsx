"use client";

import {
  ResizableHandle,
  ResizablePanel,
  ResizablePanelGroup,
} from "@gitintel/ui/resizable";
import type { FC, ReactNode } from "react";

import { Thread } from "./thread";

export const AssistantSidebar: FC<{ children: ReactNode }> = ({
  children,
}) => {
  return (
    <ResizablePanelGroup orientation="horizontal">
      <ResizablePanel>{children}</ResizablePanel>
      <ResizableHandle />
      <ResizablePanel>
        <Thread />
      </ResizablePanel>
    </ResizablePanelGroup>
  );
};
