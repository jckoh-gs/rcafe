import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import { useEffect, useRef } from 'react'
import type { GeoPoint, RecommendationItem } from '../../../shared/api'
import { MAP_ATTRIBUTION, MAP_TILE_URL } from '../../../shared/config'
import './LocationMap.css'

interface Props {
  /** Area the recommendations are for. */
  applied: GeoPoint
  /** Pin the user moved but has not confirmed. */
  pending: GeoPoint | null
  items: RecommendationItem[]
  onPick: (point: GeoPoint) => void
}

const pinIcon = L.divIcon({
  className: 'map-pin',
  html: '<span class="map-pin__head"></span><span class="map-pin__tip"></span>',
  iconSize: [32, 42],
  iconAnchor: [16, 40],
})

function cafeIcon(rank: number): L.DivIcon {
  return L.divIcon({
    className: 'map-cafe',
    html: `<span>${rank}</span>`,
    iconSize: [30, 30],
    iconAnchor: [15, 15],
  })
}

/** Tap/click the map or drag the pin to choose another area. */
export function LocationMap({ applied, pending, items, onPick }: Props) {
  const container = useRef<HTMLDivElement>(null)
  const map = useRef<L.Map | null>(null)
  const pin = useRef<L.Marker | null>(null)
  const cafeLayer = useRef<L.LayerGroup | null>(null)
  const pickRef = useRef(onPick)

  useEffect(() => {
    pickRef.current = onPick
  }, [onPick])

  useEffect(() => {
    if (!container.current || map.current) return
    const instance = L.map(container.current, { zoomControl: true }).setView([applied.lat, applied.lng], 15)
    L.tileLayer(MAP_TILE_URL, { maxZoom: 19, attribution: MAP_ATTRIBUTION }).addTo(instance)
    cafeLayer.current = L.layerGroup().addTo(instance)
    const marker = L.marker([applied.lat, applied.lng], { icon: pinIcon, draggable: true, zIndexOffset: 1000 })
    marker.addTo(instance)
    marker.on('dragend', () => {
      const { lat, lng } = marker.getLatLng()
      pickRef.current({ lat, lng })
    })
    instance.on('click', (event: L.LeafletMouseEvent) => {
      pickRef.current({ lat: event.latlng.lat, lng: event.latlng.lng })
    })
    pin.current = marker
    map.current = instance
    return () => {
      instance.remove()
      map.current = null
      pin.current = null
      cafeLayer.current = null
    }
    // The map is created once; later changes are applied by the effects below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // Pin follows the pending point (or snaps back to the applied area).
  useEffect(() => {
    const target = pending ?? applied
    pin.current?.setLatLng([target.lat, target.lng])
  }, [applied, pending])

  // Numbered cafe markers; frame them together with the origin when the results change.
  useEffect(() => {
    const layer = cafeLayer.current
    const instance = map.current
    if (!layer || !instance) return
    layer.clearLayers()
    const points: L.LatLngExpression[] = [[applied.lat, applied.lng]]
    for (const item of items) {
      const latlng: L.LatLngExpression = [item.cafe.lat, item.cafe.lng]
      points.push(latlng)
      L.marker(latlng, { icon: cafeIcon(item.rank), keyboard: false })
        .bindTooltip(`${item.rank}. ${item.cafe.name}`, { direction: 'top', offset: [0, -12] })
        .addTo(layer)
    }
    instance.fitBounds(L.latLngBounds(points), { padding: [36, 36], maxZoom: 16, animate: false })
  }, [applied, items])

  return (
    <section className="location-map" aria-label="지역 선택 지도">
      <div ref={container} className="location-map__canvas" />
      <p className="location-map__hint">
        지도를 누르거나 핀을 끌어서 다른 지역을 골라 보세요. 숫자는 추천 순위예요.
      </p>
    </section>
  )
}
