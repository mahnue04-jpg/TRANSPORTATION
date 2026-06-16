import React from "react";

export interface BaseCardProps {
  className?: string;
  children: React.ReactNode;
  onClick?: () => void;
  role?: string;
  ariaLabel?: string;
}

export function BaseCard({ className = "", children, onClick, role, ariaLabel }: BaseCardProps) {
  const interactive = typeof onClick === "function";
  return (
    <div
      className={`amicor-card ${className}`.trim()}
      onClick={onClick}
      role={role || (interactive ? "button" : undefined)}
      aria-label={ariaLabel}
      tabIndex={interactive ? 0 : undefined}
    >
      {children}
    </div>
  );
}
