import type { Traffic } from '../types'

export function TrafficDot({ value, label }: { value: Traffic; label?: string }) {
  return (
    <span className={`traffic traffic-${value}`}>
      {label ?? value}
    </span>
  )
}
