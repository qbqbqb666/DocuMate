import { useState, type ComponentProps } from 'react'

export function PasswordInput(props: Omit<ComponentProps<'input'>, 'type'>) {
  const [visible, setVisible] = useState(false)
  const action = visible ? '隐藏密码' : '显示密码'
  return <div style={{ position: 'relative' }}>
    <input {...props} type={visible ? 'text' : 'password'} style={{ ...props.style, paddingRight: 48 }} />
    <button type="button" aria-label={action} title={action} aria-pressed={visible} disabled={props.disabled}
      onMouseDown={event => event.preventDefault()} onClick={() => setVisible(value => !value)}
      className="!bg-transparent hover:!bg-[var(--dm-accent-soft)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--dm-accent)] disabled:opacity-50"
      style={{ position: 'absolute', right: 6, top: '50%', transform: 'translateY(-50%)', display: 'grid',
        placeItems: 'center', width: 36, height: 36, minWidth: 0, minHeight: 0, margin: 0, padding: 0,
        border: 0, borderRadius: 8, color: 'var(--dm-accent)' }}>
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"
        strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        {visible ? <><path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12Z" /><circle cx="12" cy="12" r="3" /></>
          : <><path d="m3 3 18 18M10.6 5.1 12 5c6.5 0 10 7 10 7a19 19 0 0 1-3.1 4M6.2 6.2A21 21 0 0 0 2 12s3.5 7 10 7a11 11 0 0 0 5.8-1.8M9.9 9.9a3 3 0 0 0 4.2 4.2" /></>}
      </svg>
    </button>
  </div>
}
