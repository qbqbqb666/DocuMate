type IconName = 'folder' | 'grid' | 'message' | 'search' | 'upload' | 'chevron' | 'plus' | 'more' | 'file' | 'bot' | 'settings' | 'close' | 'external' | 'clock' | 'send' | 'stop' | 'sparkle' | 'database' | 'logout' | 'check'

export function Icon({ name, size = 18, stroke = 1.9 }: { name: IconName; size?: number; stroke?: number }) {
  const common = { fill: 'none', stroke: 'currentColor', strokeWidth: stroke, strokeLinecap: 'round' as const, strokeLinejoin: 'round' as const }
  const paths: Record<IconName, React.ReactNode> = {
    folder: <path {...common} d="M3 6.5h6l2 2h10v10.5a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V6.5Z" />,
    grid: <><rect {...common} x="3" y="3" width="7" height="7" rx="1"/><rect {...common} x="14" y="3" width="7" height="7" rx="1"/><rect {...common} x="3" y="14" width="7" height="7" rx="1"/><rect {...common} x="14" y="14" width="7" height="7" rx="1"/></>,
    message: <path {...common} d="M4 5.5h16v11H9l-5 4v-15Z" />,
    search: <><circle {...common} cx="10.5" cy="10.5" r="6.5"/><path {...common} d="m16 16 5 5"/></>,
    upload: <><path {...common} d="M12 16V3M7.5 7.5 12 3l4.5 4.5"/><path {...common} d="M4 14v5a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-5"/></>,
    chevron: <path {...common} d="m8 4 6 8-6 8" />,
    plus: <path {...common} d="M12 5v14M5 12h14" />,
    more: <path {...common} d="M5 12h.01M12 12h.01M19 12h.01" strokeWidth="3" />,
    file: <><path {...common} d="M6 3h8l4 4v14H6V3Z"/><path {...common} d="M14 3v5h5M9 12h6M9 16h6"/></>,
    bot: <><rect {...common} x="4" y="7" width="16" height="13" rx="3"/><path {...common} d="M12 3v4M8.5 13h.01M15.5 13h.01M9 17h6"/><circle fill="currentColor" cx="8.5" cy="13" r="1"/><circle fill="currentColor" cx="15.5" cy="13" r="1"/></>,
    settings: <><circle {...common} cx="12" cy="12" r="3"/><path {...common} d="M19 13.3v-2.6l-2-.6a5.7 5.7 0 0 0-.7-1.7l1-1.8-1.8-1.8-1.8 1a5.7 5.7 0 0 0-1.7-.7L11.3 3H8.7l-.6 2a5.7 5.7 0 0 0-1.7.7l-1.8-1-1.8 1.8 1 1.8a5.7 5.7 0 0 0-.7 1.7l-2 .6v2.6l2 .6c.2.6.4 1.2.7 1.7l-1 1.8 1.8 1.8 1.8-1c.5.3 1.1.5 1.7.7l.6 2h2.6l.6-2c.6-.2 1.2-.4 1.7-.7l1.8 1 1.8-1.8-1-1.8c.3-.5.5-1.1.7-1.7l2-.6Z"/></>,
    close: <path {...common} d="m6 6 12 12M18 6 6 18" />,
    external: <><path {...common} d="M13 4h7v7M20 4l-9 9"/><path {...common} d="M18 13v5a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h5"/></>,
    clock: <><circle {...common} cx="12" cy="12" r="8"/><path {...common} d="M12 7v5l3 2"/></>,
    send: <path {...common} d="m21 3-7.2 18-3.4-7.4L3 10.2 21 3ZM10.4 13.6 21 3" />,
    stop: <rect {...common} x="5" y="5" width="14" height="14" rx="2" />,
    sparkle: <path {...common} d="m12 2 1.7 6.3L20 10l-6.3 1.7L12 18l-1.7-6.3L4 10l6.3-1.7L12 2ZM19 16l.7 2.3L22 19l-2.3.7L19 22l-.7-2.3L16 19l2.3-.7L19 16Z"/>,
    database: <><ellipse {...common} cx="12" cy="5" rx="7" ry="3"/><path {...common} d="M5 5v7c0 1.7 3.1 3 7 3s7-1.3 7-3V5M5 12v7c0 1.7 3.1 3 7 3s7-1.3 7-3v-7"/></>,
    logout: <><path {...common} d="M10 5H5v14h5M14 8l4 4-4 4M18 12H9"/></>,
    check: <path {...common} d="m5 12 4.2 4L19 6" />,
  }
  return <svg width={size} height={size} viewBox="0 0 24 24" aria-hidden="true">{paths[name]}</svg>
}
