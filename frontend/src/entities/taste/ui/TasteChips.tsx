import type { TasteChip } from '../../../shared/api'
import './TasteChips.css'

interface Props {
  chips: TasteChip[]
  label: string
  limit?: number
}

export function TasteChips({ chips, label, limit = 3 }: Props) {
  if (chips.length === 0) return null
  return (
    <ul className="taste-chips" aria-label={label}>
      {chips.slice(0, limit).map((chip) => (
        <li key={chip.axis} className="taste-chip" data-axis={chip.axis}>
          {chip.label}
        </li>
      ))}
    </ul>
  )
}
