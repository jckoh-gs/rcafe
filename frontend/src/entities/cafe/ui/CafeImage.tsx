import { useState } from 'react'
import './CafeImage.css'

interface Props {
  src: string | null
  alt: string
}

/** Photo with a warm gradient fallback (missing or blocked images must still look intentional). */
export function CafeImage({ src, alt }: Props) {
  const [failed, setFailed] = useState(false)
  if (!src || failed) {
    return (
      <div className="cafe-image cafe-image--fallback" role="img" aria-label={`${alt} (사진 없음)`}>
        <span aria-hidden="true">☕</span>
      </div>
    )
  }
  return (
    <img
      className="cafe-image"
      src={src}
      alt={alt}
      loading="lazy"
      referrerPolicy="no-referrer"
      onError={() => setFailed(true)}
    />
  )
}
