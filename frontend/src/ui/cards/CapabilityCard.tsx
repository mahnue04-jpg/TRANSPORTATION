import React from "react";
import { BaseCard, BaseCardProps } from "./BaseCard";

export function CapabilityCard(props: BaseCardProps) {
  return <BaseCard {...props} className={`capability-card ${props.className || ""}`.trim()} />;
}
