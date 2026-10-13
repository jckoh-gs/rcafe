/** Response contract of the aicafe backend (`/api/v1/recommendations`). */

export interface OpenState {
  is_open: boolean | null
  label: string
  changes_at: string | null
  changes_tomorrow: boolean
}

export interface TasteChip {
  axis: string
  label: string
  value: number
}

export interface HoursRow {
  days: string
  text: string
  is_today: boolean
}

export interface Menu {
  name: string
  price: number | null
  image_url: string | null
}

export interface Cafe {
  place_id: string
  name: string
  address: string | null
  lat: number
  lng: number
  rating: number | null
  review_count: number
  distance_m: number
  walking_minutes: number
  naver_map_url: string
  image_url: string | null
  open_state: OpenState
  today_hours: string | null
  weekly_hours: HoursRow[]
}

export interface RecommendationItem {
  rank: number
  cafe: Cafe
  menu: Menu
  message: string
  headline: string
  reason: string
  status_line: string
  score: number
  taste_chips: TasteChip[]
}

export interface Weather {
  station_id: string
  observed_at: string
  description: string
  feels_like_c: number
  raining: boolean
  humidity_pct: number
  wanted_taste: TasteChip[]
  nearest_scenario: string
}

export interface Recommendations {
  origin_lat: number
  origin_lng: number
  radius_m: number
  weather: Weather
  summary: string
  items: RecommendationItem[]
  /** Ten more cafes after the podium (ranks 4 and up), shown behind a "show more" button. */
  more_items: RecommendationItem[]
  notices: string[]
  generated_at: string
}

export interface GeoPoint {
  lat: number
  lng: number
}

export type CollectionStatus =
  | 'none'
  | 'queued'
  | 'already_queued'
  | 'collecting'
  | 'done'
  | 'covered'

/** What happened to a visitor's request to collect an area (see /api/v1/collection-requests). */
export interface CollectionRequestResult {
  status: CollectionStatus
  request_count: number
  cafes_found: number | null
  message: string
  next_run_at: string | null
}

export type AdminStatus = 'pending' | 'running' | 'done' | 'failed'

/** One area visitors asked to have collected, as the administrator sees it. */
export interface AdminRequest {
  id: number
  cell_key: string
  lat: number
  lng: number
  radius_m: number
  status: AdminStatus
  request_count: number
  requested_at: string
  last_requested_at: string
  started_at: string | null
  finished_at: string | null
  cafes_found: number | null
  cafes_nearby: number
  note: string | null
}

export interface AdminOverview {
  collector_running: boolean
  counts: Record<AdminStatus, number>
  items: AdminRequest[]
}
