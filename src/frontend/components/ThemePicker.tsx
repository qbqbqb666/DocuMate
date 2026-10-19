import { THEMES, useTheme } from '../hooks/useTheme'
import { BrandWordmark } from './BrandWordmark'
import { Icon } from './Icon'

export function ThemePicker() {
  const { theme, setTheme } = useTheme()
  return <section className="dm-profile-section dm-theme-section" aria-labelledby="dm-theme-title">
    <div className="dm-profile-section-title"><span id="dm-theme-title"><Icon name="grid" size={17} />外观主题</span><em>本机记忆</em></div>
    <div className="dm-theme-grid">
      {THEMES.map(item => <button type="button" key={item.id} className="dm-theme-choice" aria-pressed={theme === item.id} onClick={() => setTheme(item.id)}>
        <span className="dm-theme-preview" data-theme={item.id} aria-hidden="true">
          <span className="dm-theme-preview-brand"><BrandWordmark /></span>
          <span className="dm-theme-preview-workspace"><span className="dm-theme-preview-nav"><i /><i /><i /></span><span className="dm-theme-preview-page"><b>文档与对话</b><i /><i /><i /><span><i /><i /><i /></span></span></span>
        </span>
        <span className="dm-theme-choice-title">{item.name}{theme === item.id && <Icon name="check" size={15} />}</span>
        <span className="dm-theme-choice-description">{item.description}</span>
      </button>)}
    </div>
  </section>
}
