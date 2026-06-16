import React from "react";
import { BaseCard, BaseCardProps } from "./BaseCard";

export function AssistantCard(props: BaseCardProps) {
  return <BaseCard {...props} className={`assistant-card ${props.className || ""}`.trim()} />;
}
