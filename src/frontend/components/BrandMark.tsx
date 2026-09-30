interface BrandMarkProps {
  size?: number
  className?: string
}

/** DocuMate 的折页 D 标记：大尺寸用于品牌，小尺寸用于应用图标。 */
export function BrandMark({ size = 40, className = '' }: BrandMarkProps) {
  return (
    <svg
      className={className}
      width={size}
      height={size}
      viewBox="0 0 48 48"
      fill="none"
      aria-label="DocuMate"
    >
      <rect width="48" height="48" rx="14" fill="#1E3A8A" />
      <path d="M14 11.5h12.4c5.3 0 9.6 4.3 9.6 9.6v5.8c0 5.3-4.3 9.6-9.6 9.6H14V11.5Z" stroke="white" strokeWidth="2.5" strokeLinejoin="round" />
      <path d="M14 11.5v25M19.5 18h10M19.5 23.5h10M19.5 29h7" stroke="white" strokeWidth="2.3" strokeLinecap="round" />
      <path d="M30 11.5v7.7h5.8" stroke="white" strokeWidth="2.5" strokeLinejoin="round" />
    </svg>
  )
}
