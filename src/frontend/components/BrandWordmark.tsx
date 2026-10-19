export function BrandWordmark({ className = '' }: { className?: string }) {
  return <span className={`dm-wordmark ${className}`} aria-label="DocuMate">
    <span data-word="DocuMate" aria-hidden="true">DocuMate</span>
  </span>
}
