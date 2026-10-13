export function formatPrice(price: number | null): string | null {
  return price === null ? null : `${price.toLocaleString('ko-KR')}원`
}

export function formatDistance(meters: number): string {
  return meters < 1000 ? `${Math.round(meters)}m` : `${(meters / 1000).toFixed(1)}km`
}

export function formatRating(rating: number | null): string | null {
  return rating === null ? null : rating.toFixed(1)
}

/** Great-circle distance in meters. */
export function distanceMeters(a: { lat: number; lng: number }, b: { lat: number; lng: number }): number {
  const rad = Math.PI / 180
  const dLat = (b.lat - a.lat) * rad
  const dLng = (b.lng - a.lng) * rad
  const h =
    Math.sin(dLat / 2) ** 2 + Math.cos(a.lat * rad) * Math.cos(b.lat * rad) * Math.sin(dLng / 2) ** 2
  return 2 * 6_371_000 * Math.asin(Math.sqrt(h))
}

const KST_DATE_TIME = new Intl.DateTimeFormat('ko-KR', {
  timeZone: 'Asia/Seoul',
  month: 'numeric',
  day: 'numeric',
  hour: '2-digit',
  minute: '2-digit',
  hour12: false,
})

/** "10월 11일 03:30" in Korean time, or "-" when there is no time. */
export function formatDateTime(iso: string | null): string {
  if (!iso) return '-'
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return '-'
  const part = Object.fromEntries(KST_DATE_TIME.formatToParts(date).map((p) => [p.type, p.value]))
  return `${part.month}월 ${part.day}일 ${part.hour}:${part.minute}`
}
