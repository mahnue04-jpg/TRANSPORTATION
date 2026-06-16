import React from "react";
import { BaseCard, BaseCardProps } from "./BaseCard";

export function WorkflowCard(props: BaseCardProps) {
  return <BaseCard {...props} className={`workflow-card ${props.className || ""}`.trim()} />;
}
