import { useState } from 'react'

export const THEMES = [
  { id: 'basic', name: '基础素色', description: '纸白与灰绿 · 宋体与圆体' },
  { id: 'retro', name: '复古彩层', description: '暖纸与莓红 · 印刷宋体' },
  { id: 'bubble', name: '粉色软糖', description: '浅粉与玫红 · 柔和全圆体' },
  { id: 'gold', name: '钴蓝橙金', description: '钴蓝与橙金 · 厚重圆体' },
] as const

export type ThemeId = typeof THEMES[number]['id']
const STORAGE_KEY = 'documate.theme'

function isTheme(value: string | null): value is ThemeId {
  return THEMES.some(theme => theme.id === value)
}

export function initializeTheme() {
  let theme: ThemeId = 'basic'
  try {
    const saved = localStorage.getItem(STORAGE_KEY)
    if (isTheme(saved)) theme = saved
  } catch { /* 无法持久化时仍可使用默认主题。 */ }
  document.documentElement.dataset.theme = theme
}

export function useTheme() {
  const [theme, setCurrentTheme] = useState<ThemeId>(() => {
    const current = document.documentElement.dataset.theme || null
    return isTheme(current) ? current : 'basic'
  })

  const setTheme = (next: ThemeId) => {
    document.documentElement.dataset.theme = next
    setCurrentTheme(next)
    try { localStorage.setItem(STORAGE_KEY, next) } catch { /* 本次切换仍然生效。 */ }
  }

  return { theme, setTheme }
}
