import { useState } from 'react'
import { BrandWordmark } from '../components/BrandWordmark'
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
    <div className="auth-mini-stats"><span><i />测试阶段</span></div>
  </aside>
}

function Robot({ name, images, onHover }: { name: string; images: [string, string, string]; onHover: (value: boolean) => void }) {
  return <div className={`robot ${name}`} onMouseEnter={() => onHover(true)} onMouseLeave={() => onHover(false)}>
    <img className="state-idle" src={images[0]} alt="" /><img className="state-peek" src={images[1]} alt="" /><img className="state-smile" src={images[2]} alt="" />
  </div>
}

function Wordmark() {
  return <div className="auth-wordmark" aria-label="DocuMate">
    <BrandWordmark />
  </div>
}
