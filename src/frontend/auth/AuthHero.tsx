import { useState } from 'react'
import r1Idle from '../design/UI-Design v1/assets/robots/robot-1-idle.png'
import r1Peek from '../design/UI-Design v1/assets/robots/robot-1-peek.png'
import r1Smile from '../design/UI-Design v1/assets/robots/robot-1-smile.png'
import r2Idle from '../design/UI-Design v1/assets/robots/robot-2-idle.png'
import r2Peek from '../design/UI-Design v1/assets/robots/robot-2-peek.png'
import r2Smile from '../design/UI-Design v1/assets/robots/robot-2-smile.png'
import r3Idle from '../design/UI-Design v1/assets/robots/robot-3-idle.png'
import r3Peek from '../design/UI-Design v1/assets/robots/robot-3-peek.png'
import r3Smile from '../design/UI-Design v1/assets/robots/robot-3-smile.png'

export type RobotMood = 'idle' | 'peek' | 'smile'

export function AuthHero({ mood }: { mood: RobotMood }) {
  const [hoveringRobot, setHoveringRobot] = useState(false)
  const state = hoveringRobot ? 'smile' : mood
  return <aside className="auth-hero">
    <div className="auth-orb auth-orb-one" /><div className="auth-orb auth-orb-two" />
    <Wordmark />
    <div className={`auth-robot-scene ${state}`}>
      <Robot name="robot-one" images={[r1Idle, r1Peek, r1Smile]} onHover={setHoveringRobot} />
      <Robot name="robot-two" images={[r2Idle, r2Peek, r2Smile]} onHover={setHoveringRobot} />
      <Robot name="robot-three" images={[r3Idle, r3Peek, r3Smile]} onHover={setHoveringRobot} />
    </div>
    <div className="auth-mini-stats"><span><i />测试阶段</span><b>·</b><code>12k+ 文档</code><b>·</b><code>1.8M chunks</code><b>·</b><code>0 数据上云</code></div>
  </aside>
}

function Robot({ name, images, onHover }: { name: string; images: [string, string, string]; onHover: (value: boolean) => void }) {
  return <div className={`robot ${name}`} onMouseEnter={() => onHover(true)} onMouseLeave={() => onHover(false)}>
    <img className="state-idle" src={images[0]} alt="" /><img className="state-peek" src={images[1]} alt="" /><img className="state-smile" src={images[2]} alt="" />
  </div>
}

function Wordmark() {
  return <div className="auth-wordmark" aria-label="DocuMate">
    <svg className="auth-wordmark-d" viewBox="0 0 130 160" aria-hidden="true"><defs><linearGradient id="auth-page-grad" x1="0" y1="0" x2="1" y2="1"><stop offset="0%" stopColor="#dbe4f7" /><stop offset="100%" stopColor="#6b85d4" /></linearGradient></defs><path d="M18 6v148h46c38 0 60-30 60-74S102 6 64 6H18Z" fill="#fff" /><g transform="translate(36 56)"><path d="M0 4 30 0v50L0 46Z" fill="#1e3a8a" /><path d="m30 0 30 4v42l-30 4Z" fill="#1e3a8a" /><path d="M30 2v46M5 14l21-2M5 22l22-2M5 30l20-2" stroke="#fff" strokeWidth=".9" opacity=".55" /><g className="auth-inner-page"><path d="m30 0 30 4v42l-30 4Z" fill="url(#auth-page-grad)" stroke="#1e3a8a" strokeWidth="1.4" /><path d="m34 12 22 2m-22 6 23 2" stroke="#1e3a8a" strokeWidth=".9" opacity=".55" /></g></g></svg>
    <span>o</span><span>c</span><span>u</span><span className="soft">M</span><span className="soft">a</span><span className="soft">t</span><span className="soft">e</span>
    <p>懂你文档的 AI 助手 <i /> 数据本地优先</p>
  </div>
}
