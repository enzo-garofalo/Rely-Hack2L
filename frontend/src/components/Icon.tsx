import type { ReactElement } from "react";

export type IconName =
  | "activity" | "alert-circle" | "arrow-right" | "check" | "check-check" | "check-circle"
  | "chevron-down" | "chevron-right" | "clock" | "database" | "git-commit" | "help-circle"
  | "home" | "inbox" | "link" | "message-circle" | "message-square" | "mic" | "more-horizontal"
  | "package" | "quote" | "rotate-ccw" | "send" | "server" | "shield-check" | "sparkles"
  | "square" | "users" | "volume-2" | "x" | "zap";

const paths: Record<IconName, ReactElement> = {
  activity: <><polyline points="22 12 18 12 15 21 9 3 6 12 2 12" /></>,
  "alert-circle": <><circle cx="12" cy="12" r="9" /><line x1="12" y1="8" x2="12" y2="12" /><line x1="12" y1="16" x2="12.01" y2="16" /></>,
  "arrow-right": <><line x1="5" y1="12" x2="19" y2="12" /><polyline points="13 6 19 12 13 18" /></>,
  check: <polyline points="20 6 9 17 4 12" />,
  "check-check": <><polyline points="18 6 7 17 2 12" /><polyline points="22 10 13 19 11 17" /></>,
  "check-circle": <><circle cx="12" cy="12" r="9" /><polyline points="8 12 11 15 16 9" /></>,
  "chevron-down": <polyline points="6 9 12 15 18 9" />,
  "chevron-right": <polyline points="9 18 15 12 9 6" />,
  clock: <><circle cx="12" cy="12" r="9" /><polyline points="12 7 12 12 16 14" /></>,
  database: <><ellipse cx="12" cy="5" rx="8" ry="3" /><path d="M4 5v6c0 1.7 3.6 3 8 3s8-1.3 8-3V5" /><path d="M4 11v6c0 1.7 3.6 3 8 3s8-1.3 8-3v-6" /></>,
  "git-commit": <><circle cx="12" cy="12" r="3" /><line x1="3" y1="12" x2="9" y2="12" /><line x1="15" y1="12" x2="21" y2="12" /></>,
  "help-circle": <><circle cx="12" cy="12" r="9" /><path d="M9.5 9a2.6 2.6 0 1 1 4.1 2.1c-.9.6-1.6 1.1-1.6 2.4" /><line x1="12" y1="17" x2="12.01" y2="17" /></>,
  home: <><path d="M3 11l9-8 9 8" /><path d="M5 10v10h14V10" /><path d="M9 20v-6h6v6" /></>,
  inbox: <><rect x="3" y="4" width="18" height="16" rx="2" /><path d="M3 13h5l2 3h4l2-3h5" /></>,
  link: <><path d="M10 13a5 5 0 0 0 7.5.5l2-2a5 5 0 0 0-7-7l-1 1" /><path d="M14 11a5 5 0 0 0-7.5-.5l-2 2a5 5 0 0 0 7 7l1-1" /></>,
  "message-circle": <path d="M21 11.5a8.4 8.4 0 0 1-9 8.5 9.6 9.6 0 0 1-4-.9L3 21l1.8-4.3A8.5 8.5 0 1 1 21 11.5z" />,
  "message-square": <><path d="M21 15a4 4 0 0 1-4 4H8l-5 3V7a4 4 0 0 1 4-4h10a4 4 0 0 1 4 4z" /><line x1="8" y1="9" x2="16" y2="9" /><line x1="8" y1="13" x2="13" y2="13" /></>,
  mic: <><rect x="9" y="2" width="6" height="12" rx="3" /><path d="M5 10a7 7 0 0 0 14 0" /><line x1="12" y1="17" x2="12" y2="22" /><line x1="8" y1="22" x2="16" y2="22" /></>,
  "more-horizontal": <><circle cx="5" cy="12" r="1" /><circle cx="12" cy="12" r="1" /><circle cx="19" cy="12" r="1" /></>,
  package: <><path d="M21 16V8a2 2 0 0 0-1-1.7l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.7l7 4a2 2 0 0 0 2 0l7-4a2 2 0 0 0 1-1.7z" /><polyline points="3.3 7 12 12 20.7 7" /><line x1="12" y1="22" x2="12" y2="12" /></>,
  quote: <><path d="M9 11H5a4 4 0 0 1 4-4v8a4 4 0 0 1-4 4" /><path d="M19 11h-4a4 4 0 0 1 4-4v8a4 4 0 0 1-4 4" /></>,
  "rotate-ccw": <><polyline points="1 4 1 10 7 10" /><path d="M3.5 15a9 9 0 1 0 2-9.5L1 10" /></>,
  send: <><line x1="22" y1="2" x2="11" y2="13" /><polygon points="22 2 15 22 11 13 2 9 22 2" /></>,
  server: <><rect x="3" y="4" width="18" height="6" rx="2" /><rect x="3" y="14" width="18" height="6" rx="2" /><line x1="7" y1="7" x2="7.01" y2="7" /><line x1="7" y1="17" x2="7.01" y2="17" /></>,
  "shield-check": <><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" /><polyline points="9 12 11 14 15 9" /></>,
  sparkles: <><path d="M12 3l1.4 4.1L17.5 8.5l-4.1 1.4L12 14l-1.4-4.1-4.1-1.4 4.1-1.4z" /><path d="M19 15l.8 2.2L22 18l-2.2.8L19 21l-.8-2.2L16 18l2.2-.8z" /></>,
  square: <rect x="6" y="6" width="12" height="12" rx="1" />,
  users: <><path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2" /><circle cx="9" cy="7" r="4" /><path d="M22 21v-2a4 4 0 0 0-3-3.9" /><path d="M16 3.1a4 4 0 0 1 0 7.8" /></>,
  "volume-2": <><polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5" /><path d="M15.5 8.5a5 5 0 0 1 0 7" /><path d="M19 5a10 10 0 0 1 0 14" /></>,
  x: <><line x1="18" y1="6" x2="6" y2="18" /><line x1="6" y1="6" x2="18" y2="18" /></>,
  zap: <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2" />,
};

export function Icon({ name, size = 18, className }: { name: IconName; size?: number; className?: string }) {
  return <svg className={className} width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{paths[name]}</svg>;
}
