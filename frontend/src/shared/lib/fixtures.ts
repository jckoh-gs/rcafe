import type { RecommendationItem, Recommendations } from '../api'

/** Shared test data shaped like the real API response. */
export function makeRecommendations(overrides: Partial<Recommendations> = {}): Recommendations {
  const item = (rank: number, name: string, menu: string, open: boolean | null): RecommendationItem => ({
    rank,
    cafe: {
      place_id: String(rank),
      name,
      address: '서울 강남구 테헤란로 1',
      lat: 37.5 + rank / 1000,
      lng: 127.03,
      rating: 4.6,
      review_count: 1234,
      distance_m: 300 * rank,
      walking_minutes: 4 * rank,
      naver_map_url: `https://map.naver.com/p/entry/place/${rank}`,
      image_url: rank === 3 ? null : `https://img.test/${rank}.jpg`,
      today_hours: open === null ? null : open ? '08:00 ~ 22:00' : '17:00 ~ 23:00',
      weekly_hours:
        open === null
          ? []
          : [
              { days: '월~금', text: '08:00 ~ 22:00', is_today: open },
              { days: '토', text: '10:00 ~ 18:00', is_today: !open },
              { days: '일', text: '정기휴무', is_today: false },
            ],
      open_state: {
        is_open: open,
        label: open === null ? '영업 정보 없음' : open ? '영업 중' : '영업 종료',
        changes_at: open === null ? null : open ? '22:00' : '09:00',
        changes_tomorrow: open === false,
      },
    },
    menu: { name: menu, price: 5500, image_url: null },
    message: `${name}의 ${menu}를 추천드려요.`,
    headline: `${name}의 ${menu}를 추천드려요 ✨ 상큼한 맛이라 오늘 날씨에 잘 어울려요.`,
    reason: '상큼한 맛이라 오늘 날씨에 잘 어울려요.',
    status_line: '도보 약 4분, 지금 영업 중이에요.',
    score: 0.8,
    taste_chips: [
      { axis: 'sour_fresh', label: '상큼함', value: 0.9 },
      { axis: 'light', label: '가볍고 산뜻한', value: 0.7 },
    ],
  })
  return {
    origin_lat: 37.5006,
    origin_lng: 127.0364,
    radius_m: 1000,
    weather: {
      station_id: '108',
      observed_at: '2026-10-10T08:00:00+09:00',
      description: '선선한 맑은 아침',
      feels_like_c: 14.2,
      raining: false,
      humidity_pct: 63,
      wanted_taste: [
        { axis: 'hot', label: '따뜻함', value: 0.6 },
        { axis: 'bitter_roast', label: '깊은 로스팅', value: 0.54 },
      ],
      nearest_scenario: '선선한 맑은 아침',
    },
    summary: '지내기 좋은 선선한 날씨예요 🍃 오늘은 쌉싸름한 맛이 어울려요.',
    items: [
      item(1, '과일창고', '자몽에이드', true),
      item(2, '크림하우스', '바닐라라떼', false),
      item(3, '로스터리원', '아메리카노', null),
    ],
    more_items: [],
    notices: [],
    generated_at: '2026-10-10T00:00:00Z',
    ...overrides,
  }
}

/** `count` extra cafes ranked after the podium, as the API sends them in `more_items`. */
export function makeMoreItems(count: number): RecommendationItem[] {
  const base = makeRecommendations().items[0]
  return Array.from({ length: count }, (_, i) => {
    const rank = i + 4
    return {
      ...base,
      rank,
      cafe: { ...base.cafe, place_id: `more-${rank}`, name: `더보기카페${rank}`, distance_m: 300 * rank },
      menu: { name: `더보기메뉴${rank}`, price: 6000, image_url: null },
      headline: `더보기카페${rank}의 더보기메뉴${rank}를 추천드려요 ✨ 쌉싸름한 맛이라 오늘 날씨에 잘 어울려요.`,
    }
  })
}
