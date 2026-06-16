import React from "react";
import { BaseCard, BaseCardProps } from "./BaseCard";

export function RuntimeCard(props: BaseCardProps) {
  return <BaseCard {...props} className={`runtime-card ${props.className || ""}`.trim()} />;
}
