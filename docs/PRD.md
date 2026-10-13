# PRD: aicafe — 날씨 맞춤 카페·메뉴 추천 서비스

> 상태: v1.0 (2026-10-10) · M0~M5 완료, k3s(`aicafe`)에 배포됨 — http://rcafe.koh.it.kr
> v0.2 변경: 사용자 답변 10건 반영(§2), 네이버 상세 페이지·KMA 실측 결과(§4.4), 영업상태 표시 규칙(§7), 말투 확정(§8), Traefik 이슈(§10.1).
> 이 문서는 확정 사항 / 실측으로 확인한 사실 / 가정 / 필요한 정보 요청을 구분해서 적는다.
> v1.1(2026-10-10): 로컬 LLM(Ollama)은 시험해 본 뒤 **전부 삭제**했다. 리뷰 입맛 태깅은 한국어 키워드 사전만 쓴다(근거: `docs/taste-model.md`).

## 1. 배경과 목표
사용자의 현재 위치(또는 지도에서 고른 지역)의 **현재 날씨**로 "지금 어울리는 입맛"을 정하고, 그 입맛에 가장 잘 맞는
**카페 + 메뉴 TOP 3**를 자연스러운 안내 멘트와 함께 보여준다.

성공 기준(MVP)
- 역삼역 반경 내 카페 데이터가 DB에 적재되어 있고, 좌표만으로 추천 3건이 1초 이내(p95 500ms 목표)에 나온다.
- 1·2·3순위 각각 입맛, 카페 정보, 메뉴, 추천 이유가 들어간 멘트가 어색하지 않다(수동 평가 20건 중 90% 이상 "자연스럽다").
- 같은 `place_id`를 다시 수집해도 중복 행이 생기지 않고 최신 값으로 갱신된다.
- k3s(`charles-k3s` / 네임스페이스 `aicafe`)에 배포되어 웹에서 위치 변경·지도 선택이 동작한다.

## 2. 확정된 결정 (사용자 답변 반영)
| 항목 | 결정 |
|---|---|
| 카페 데이터 수집 | 네이버 지도 내부 API 크롤링 (개인/PoC 한정, 상용화 시 재검토) |
| 모델 | 리뷰 분석은 **한국어 키워드 사전**, 멘트는 템플릿. 외부 AI API 없음. 로컬 LLM(Ollama)은 시험 후 삭제(사전이 더 정확하고 빠름) |
| DB | `aicafe` 네임스페이스에 **pgvector Postgres 신규** (기존 `postgress` 네임스페이스 DB는 건드리지 않음) |
| 네임스페이스 | `aicafe` 신규 생성. (이미 있는 `aiccafe`는 오타로 보이며 이 프로젝트에서 사용하지 않는다. 정리는 사용자 몫) |
| 배포 | k3s, kube context `charles-k3s`, 모든 명령에 `--context charles-k3s -n aicafe` 명시 |
| 백엔드/프론트 | 저장소 룰 준수: FastAPI + 헥사고날 / React + FSD. 모바일(Flutter)은 이번 범위 밖 |
| 수집 범위 | 중심 역삼역 (x 127.0363766, y 37.5006431), 반경 약 2km, 카페당 방문자 리뷰 **최대 10개** |
| 리뷰 저장 | 입맛 태그 + 짧은 근거 문장만 저장 (원문 장기 보관 안 함) |
| 멘트 톤 | 존댓말 + 이모지 |
| 영업상태 | 필터하지 않고 **영업 중/종료를 표시**. 단 추천 결과에 **영업 중인 곳이 2건 이상** 포함되어야 함 (§7) |
| 이미지 | 플레이스 제공 메뉴 이미지가 있으면 사용, 없으면 방문자 리뷰 사진 |
| 날씨 | 제공된 KMA `kma_sfctm2` URL 그대로 사용. 호출 한도가 작으므로 같은 지역·가까운 시각이면 **관측값 재사용** (§4.4) |
| 로컬 모델 | (철회) Ollama + 태깅 모델 + 임베딩 계획은 취소하고 삭제함 |
| Ingress | **Traefik** (사용자가 ingress-nginx를 제거함). 단 Traefik `Service`가 아직 없음 → §10.1 |
| 서비스 주소 | **`rcafe.koh.it.kr`**, **TLS 없음(HTTP)** |
| 지도 | **Leaflet + OSM**으로 먼저 구현(지도 제공자 포트 분리), NCP Maps 키가 생기면 네이버 지도로 교체 |
| 네임스페이스 | `aicafe` 생성 완료(사용자), `aiccafe`는 정리됨 |

## 3. 범위
**In (MVP)**: 역삼역 주변 카페 크롤링·DB 적재, 리뷰 기반 입맛 일반화, 날씨→입맛 벡터 검색, 좌표 기반 TOP3 추천과 멘트,
웹 UI(현재 위치 + 지도에서 지역 선택), k3s 배포.
**Out (이후)**: 로그인·개인화·즐겨찾기, 예보 기반 추천, 영업시간 필터, 네이티브 앱, 역삼 외 전국 확장 운영, 결제·예약.

## 4. 실측으로 확인한 사실 (조사 결과)

### 4.1 네이버 instant-search (실제 1회 호출)
- `GET https://map.naver.com/p/api/search/instant-search?query=카페&coords=<lat>,<lng>` → HTTP 200, JSON.
- **한 번에 `place` 10건만** 반환. 필드: `id`(=place ID), `title`, `x`(경도), `y`(위도), `dist`(km), `ctg`(카테고리),
  `jibunAddress`, `roadAddress`, `review.count`(리뷰 수), `totalScore`(검색 랭킹 점수, 별점 아님), `hasBooking`.
- **메뉴·리뷰 본문·별점·영업시간·전화는 없다.** 응답의 `menu`, `menuForWeb`는 비어 있다.
  → 이 데이터는 플레이스 상세 페이지 HTML에서 얻을 수 있음을 M0에서 확인했다(§4.4).
- 10건 제한 때문에 커버리지는 **좌표 격자 × 키워드 변형**(카페, 커피, 디저트, 베이커리, 브런치 등)으로 확보하고 `place_id`로 병합한다.
- 요청에 준 예시 좌표(37.4617, 126.8196)는 **역삼이 아니라 광명시 인근**이다. 역삼역 중심 좌표는 약 (37.5006, 127.0364)로 가정한다(§15 확인 요청).

### 4.2 인프라 (kubectl 읽기 전용 조회)
- 단일 노드 k3s: CPU 4코어 / RAM 16GB(현재 약 6.6GB 사용) / **GPU 없음**. StorageClass: `local-path`(기본), `nas-01-delete`(NFS), `jusarang-local-retain`.
- Ingress: `nginx`(ingress-nginx, 외부 IP 121.143.126.21)와 `traefik` 두 클래스가 존재. 기존 호스트는 `*.koh.it.kr` 패턴.
- 기존 Postgres는 `postgres:15` 일반 이미지(pgvector 없음) → 새로 띄운다.
- 같은 kubeconfig에 EKS prod/dev 컨텍스트가 있으므로 **반드시 컨텍스트를 명시**한다(실수 방지).
- 로컬 LLM 현실성: GPU 없는 4코어에서는 4B급이 리뷰당 55~78초, 1.7B급도 약 13초이고 사전보다 부정확했다. → 요청 경로는 물론 오프라인 배치에서도 LLM을 쓰지 않는다.

### 4.3 날씨와 입맛의 근거 자료 (검색 결과, 근거 강도를 정직하게 표시)
| 주제 | 근거 | 강도 | 서비스 반영 |
|---|---|---|---|
| 온도와 단맛 지각 | Talavera et al., *Nature* 2005, TRPM5 열 활성화로 단맛 반응이 온도(15–35°C)에 의존(주로 마우스). 사람 대상 효과는 작고 일관되지 않다는 후속 보고 | 중(기전)·약(사람) | 아이스 음료는 단맛 체감↓, 따뜻한 음료는 단맛 체감↑ → 더운 날 아이스+상큼/덜 단 쪽, 추운 날 따뜻+단/고소 쪽 가중치 |
| 외기온과 음료·식품 선택 | 일본 성인 242명: 기온 1°C↑ 시 음료 수분↑ (Frontiers/Eur J Clin Nutr 계열), 미국 소매 스캐너: 27°C 이상에서 청량음료 구매 비선형 증가(2024 학회 초록), 저온에서는 쾌락적(hedonic) 식품 선택↑(Warwick 연구 초록) | 중~약(초록·예비) | 더위: 시원·청량, 추위: 따뜻·달콤·진한 "위로" 메뉴 |
| 날씨와 기분 | Denissen et al. 2008(독일 1,233명): 평균 효과 **작음**, 개인차 큼. Keller et al. 2005: 봄에 기온·기압↑와 긍정 기분이 연관, 다른 계절엔 불일치 | **약** | 기분 축은 "보조 가중치"만 허용. 멘트에서 "비 오면 우울" 같은 단정 금지 |
| 습도·기온과 후각 | Kuehn 등 기후챔버 75명: 습도가 높으면 냄새 역치 낮아짐(더 잘 맡음). 가상 화장실 연구: 고온다습이면 냄새 강도 평가↓. 클리닉 연구(10명)는 영향 없음 | 약~혼재 | 습한/비 오는 날 향 중심 메뉴(고소·로스티·스파이시) 소폭 가산. 확정 근거로 쓰지 않음 |

결론: 근거는 **방향성은 있으나 효과 크기는 작고 혼재**한다. 따라서 날씨→입맛 매핑은 "과학적 사실"이 아니라
**근거 기반 휴리스틱 + 튜닝 가능한 가중치**로 설계하고, 멘트에서도 단정 표현을 피한다. 출처 링크는 `docs/evidence.md`에 정리한다
(Talavera 2005 *Nature* 438:1022 · Denissen 2008 *Emotion* · Keller 2005 *Psychol Sci* · Kuehn 등 olfactory thresholds · Spence 등 ambient temperature & drinks).
M0에서 원문(초록 외)을 재확인하고 인용을 확정한다.

### 4.4 M0 실측 결과 (2026-10-09, 소량 호출)

**네이버 플레이스 상세** — `GET https://pcmap.place.naver.com/place/{id}/home` 와 `/place/{id}/review/visitor`
- 로그인·쿠키 **불필요**(브라우저 UA + Referer만으로 HTTP 200). 받은 curl의 세션 쿠키는 쓰지 않으며 저장소에 넣지 않는다.
  (`/cafe/{id}/home`, `m.place.naver.com`은 404)
- 서버 렌더링 HTML 안의 `window.__APOLLO_STATE__` JSON을 파싱하면 된다(GraphQL 별도 호출 불필요). 6개 카페 표본 모두 파싱 성공.
- 얻을 수 있는 값:
  - 기본: 이름, 좌표, 주소, 전화, 편의시설, 평점(`visitorReviewsScore`), 방문자 리뷰 수, `microReviews`(한 줄 요약)
  - **영업상태**: `newBusinessHours[0].businessStatusDescription.status` = "영업 중" / "영업 종료" + 오늘 영업시간, 종료/시작 시각 설명
  - **메뉴**: `PlaceMenuItem`(일반 매장, 5/6곳) 또는 `PlaceDetail_BaeminMenu`(배달 연동 매장: 이름·가격·설명·이미지, 설명에 "당도 1.5/5" 같은 값이 있는 경우도 있음) + `menuImages`(메뉴판 사진)
  - **리뷰 통계**: `VisitorReviewStatsResult.analysis.menus`(리뷰에서 언급된 메뉴와 횟수, 예: 커피 422·라떼 392), `themes`(맛/분위기/서비스 건수), 사진 리뷰 수
  - **방문자 리뷰 본문**: `/restaurant/{id}/review/visitor`(cafe는 restaurant 타입; `/place/`는 302 리다이렉트) 페이지가 `size:10, includeContent:true` 쿼리로 **10건**(평점, 본문, 사진, 방문일, 주문 메뉴 `item.name`, 네이버 투표 키워드 `votedKeywords` 예: "커피가 맛있어요")을 이미 담고 있다. 요구(최대 10개)와 일치하므로 이 목록만 사용. 정렬은 기본(추천순) 기준
  - 사진: `topPhotos`, 리뷰 `media[].thumbnail`
- 주의점
  - 리뷰에 **광고성·AI 생성 문구**가 섞여 있다(예: "물론! … 두 가지 말투로 바꿔볼게요" 같은 챗봇 응답이 그대로 올라온 리뷰). → 태깅 전 노이즈 필터(길이, 메타 문구, 중복) 필요
  - 케이크 전문점(21케이크, 트리오드)도 `카페,디저트`로 잡힌다 → 음료 메뉴가 없는 곳은 후보에서 제외하거나 가중치 하향
  - 이미지는 `pstatic.net` 도메인. 핫링크 가능 여부와 저작권은 별도 확인 → 우선 URL만 저장하고 프록시/캐시는 하지 않음(§14)

**KMA `kma_sfctm2`**
- 호출 1회로 **전국 지상관측소(ASOS) 97곳**의 해당 시각 관측이 한 번에 온다(`stn=0`). 응답은 **EUC-KR 텍스트**, 공백 구분, 주석(`#`)에 46개 컬럼 정의.
  쓸 값: TA 기온, TD 이슬점, HM 습도, WS 풍속, RN/RN_INT 강수, CA_TOT 운량, VS 시정, SS 일조, SI 일사, WW/WC 현재일기.
- 결측은 `-9`, `-99`. 야간에는 SS/SI가 `-9`가 정상. 강수 `RN=-9`가 "비 안 옴"인지 "미관측"인지는 비 오는 날 표본으로 M1에서 확인(우선 WW/WC·CA·RN_INT로 보조 판정).
- 정각 직후에는 해당 시각 자료가 없을 수 있어 **직전 시각으로 폴백**. 첫 호출은 30초 타임아웃, 재시도는 0.3초에 성공 → 타임아웃 60초 + 1회 재시도.
- **호출 한도 대응**: 한 번 받은 스냅샷은 시각(tm) 단위로 캐시하고, 요청 지역이 달라도 같은 스냅샷에서 가장 가까운 관측소를 골라 쓴다. 사용자 요청은 캐시만 읽고, 갱신은 백엔드 단일 워커가 시각당 최대 1회 수행한다(예: 10시 30분 요청은 10시 관측값 재사용).
- 서울권 ASOS 관측소는 서울(108) 등이며 역삼 일대와 몇 km 떨어져 있다. 관측소별 **좌표표가 필요**한데, 이 키로는 지점정보 API(`stn_inf`)가 **403(권한 없음)** 이다 → §15에서 요청.

## 5. 입맛 일반화 모델

### 5.1 입맛 축 (Taste Axes, 값 0~1)
`hot`(따뜻함 선호) · `iced`(차가움 선호) · `sweet`(단맛) · `sour_fresh`(상큼·청량) · `bitter_roast`(쓴맛·로스팅) ·
`rich_creamy`(진함·크리미) · `nutty_cozy`(고소·포근) · `aroma`(향 중심: 허브/꽃/시트러스/스파이스) · `light`(가벼움) · `caffeine_boost`(각성).
각 축은 한국어 라벨과 메뉴 예시를 가진 사전(`taste_axis`)으로 관리한다. 축 목록은 사용자 승인 대상(§15).

### 5.2 날씨 → 입맛
- 입력 파라미터(KMA `kma_sfctm2`, 지상관측): 기온 TA, 습도 HM, 강수 RN, 풍속 WS, 일조/일사(SS/SI), 운량 CA 등.
  `help=1` 응답의 컬럼 정의로 M0에서 확정. **결측값(-9 등)은 인접 관측소/직전 시각으로 보정**.
- 파생 값: 체감온도(기온·풍속·습도), `is_raining`, `daylight_bucket`(시간대), `season`.
- **날씨 특징 벡터**: 정규화(0~1)한 [체감온도, 습도, 강수, 풍속, 일조/운량, 시간대 sin/cos, 계절 sin/cos].
- **벡터DB(pgvector)**: `taste_archetype`(약 20~30개 대표 입맛: "무더위 청량 아이스", "비 오는 날 따뜻 고소", "추운 아침 진한 단맛"…)와
  시나리오 격자에서 생성한 **날씨 특징 벡터 → 입맛 축 벡터** 레코드를 저장한다.
  요청 시 현재 날씨 벡터로 **top-k 근접 검색(코사인/L2) → 거리 가중 평균으로 입맛 벡터 산출**.
  규칙 엔진(근거표의 방향성)이 시드 데이터를 만들고, 벡터 검색이 부드러운 보간을 담당한다. 이후 피드백으로 갱신 가능.
- 날씨 임베딩에는 **언어 모델이 필요 없다**(수치 벡터). 임베딩 모델은 §5.3 용도로만 쓴다.

### 5.3 카페 → 입맛 (리뷰·메뉴 분석)
- 오프라인 배치: 리뷰 문장을 **한국어 키워드 사전**으로 태깅(부정·비슷한 단어·가게 묘사 제외). 손 라벨 120건으로 측정(실제 리뷰 요약 기준 블라인드 세트 F1 0.82 — 이 원본은 저작권·개인정보 때문에 저장소에서 뺐고, 저장소에는 가상 문장 120건의 회귀 테스트만 있다. `docs/taste-model.md`).
- 카페 입맛 벡터 = 리뷰 태그 빈도 × 감성 × 최신성 가중 평균, 리뷰 수가 적으면 전체 평균으로 수축(베이지안 스무딩).
- 메뉴 정규화: 메뉴명·설명 → 규칙으로 입맛과 아이스/핫을 정한다(`menu_vector`). 임베딩은 쓰지 않는다.
- 저장은 **파생 데이터 중심**: 태그, 점수, 짧은 근거 문장(길이 제한), 해시. 리뷰 원문 장기 보관은 하지 않는 방향(§15 확인).

### 5.4 추천 점수
`score = 0.55·taste_sim(cafe, weather_taste) + 0.20·quality(리뷰 수·최신성 스무딩) + 0.15·distance_decay + 0.10·menu_fit`
(가중치는 설정값, 오프라인 평가로 조정). 카페별로 입맛에 가장 맞는 **메뉴 1개**를 고른다. 추가 규칙: ① 카페에 음료가 하나라도 있으면 **음료만** 메뉴 후보가 된다(디저트는 음료가 없을 때만). ② 음료가 하나도 없는 카페는 ×0.75, 리뷰에서 음료 언급 비중이 낮은 카페(빵집 등)는 ×0.8~1.0. ③ TOP3는 브랜드당 1곳이고, 같은 음료 종류(아메리카노·라떼 등)가 겹치면 점수에서 0.05씩 감점해 구성을 다양하게 한다. ④ 추천 이유 문장은 근거가 있을 때만 쓴다: 리뷰에서 그 메뉴가 20번 이상 언급됨 → 리뷰 10건 중 3건·30% 이상이 그 메뉴와 맞는 맛을 언급 → 메뉴 자체의 맛 → 오늘 온도에 맞는 서빙 안내 순서. `uv run python -m scripts.eval_reco`로 전후를 잰다.

## 6. 데이터 수집 (Ingestion)
- 시드: 역삼역 중심(127.0363766, 37.5006431)에서 반경 약 2km, 150~300m 격자 × 키워드 6~8종으로 instant-search 호출 → `place_id` 병합.
- 상세 수집은 `place_id`별로 `home` 1회 + `review/visitor` 1회(최신 10건만 사용). 반경 2km 수백 곳이면 수천 요청 규모이므로 **검색 2초·상세 3초에 1요청 이하(1초당 1요청은 제한에 걸림), 지터, 재시도 백오프, 중단 후 재개, 응답 캐시/원본 JSONB 보관**.
  차단·스키마 변경을 감지하면 즉시 중단하고 알림(로그)한다.
- **Upsert**: `place_id`를 PK로 `INSERT … ON CONFLICT (place_id) DO UPDATE`, `content_hash`가 같으면 갱신 생략, `first_seen_at/last_crawled_at` 유지.
  리뷰는 (place_id, review_key 해시) 유니크. 사라진 장소는 `is_active=false`(삭제하지 않음).
- 실행 형태: 백엔드의 CLI(인바운드 어댑터) → 같은 이미지로 k8s `Job`/`CronJob`(수동 트리거 기본, 주기 갱신은 선택).

### 6.2 방문자 수집 요청 (한가한 시간에 실행)
데이터가 없는 지역("이 근처는 아직 준비 중이에요")에서 방문자가 **"이 지역 수집 요청하기"** 를 누르면 요청이 큐에 쌓이고, 서비스가 한가한 새벽에 모아서 수집한다.
- **접수**: `POST /api/v1/collection-requests {lat,lng}` → 약 1.1km 격자 셀(`CELL_DEG=0.01`) 단위로 합쳐 한 건으로 저장하고 요청 횟수만 올린다(많이 요청된 곳이 먼저).
  결과 상태: `queued`(접수) · `already_queued`(이미 접수됨) · `collecting`(수집 중) · `done`(수집 끝, 찾은 카페 수) · `covered`(이미 반경 1km에 카페 10곳 이상) · `busy`(대기열 100건 가득) · `limit`(새 지역은 24시간에 30곳까지).
  `GET /api/v1/collection-requests?lat&lng`는 지난 요청의 진행 상황을 돌려준다(없으면 `none`).
- **남용 방지**: 방문자(IP)당 시간당 5회(Traefik·nginx 뒤라 `X-Forwarded-For`의 뒤에서 두 번째 값을 쓴다), 대기열 상한, 일일 신규 상한. 좌표는 요청 셀의 중심만 저장한다.
- **실행**: k8s `CronJob`(`aicafe-collector`)이 매일 **03:30 KST**에 `collect-requests --budget-minutes 150 --max-requests 10`을 실행한다(`concurrencyPolicy: Forbid`).
  요청마다 반경 1.5km를 검색(격자 400m) → 메뉴·리뷰가 없는 곳만 상세 수집 → **새 카페만** 입맛 계산 → 리뷰 원문 삭제. 속도는 평소와 같이 검색 2초·상세 3초에 1회.
- **중단과 재개**: 시간 예산(150분)을 넘기면 하던 요청을 다시 대기열에 돌려놓고 멈춘다(모든 단계가 `place_id` upsert라 이어서 하면 된다). 네이버가 403/429를 주면 즉시 멈추고(종료 코드 2) 다음 날 재시도한다. 그 밖의 오류는 그 요청만 `failed`로 두고 다음 요청으로 넘어간다. `failed`이거나 끝난 지 30일이 넘은 지역은 다시 요청하면 대기열로 돌아온다.
- **확인**: `uv run python -m app.adapters.inbound.cli requests`(대기열 목록), 수동 실행은 `collect-requests --budget-minutes 8`.

### 6.3 관리자 페이지 (`/admin`)
수집 요청을 관리하는 운영용 화면. 메뉴나 링크로 노출하지 않고 주소(`/admin`)로만 들어간다.
- **로그인**: 계정은 하나, K8s Secret `aicafe-backend`의 `AICAFE_ADMIN_USER` · `AICAFE_ADMIN_PASSWORD` · `AICAFE_ADMIN_SESSION_KEY`로 준다(`deploy.sh secrets`가 없을 때만 생성, 값은 출력하지 않음). 셋 중 하나라도 비었거나 비밀번호 12자·키 24자 미만이면 관리자 API 전체가 404로 꺼진다.
  로그인하면 서명된 쿠키(HMAC, 8시간, `HttpOnly` · `SameSite=Strict` · 경로 `/api/v1/admin`)가 세션이다. 서버에 세션을 저장하지 않는다. 로그인 시도는 방문자(IP)당 10분에 10회, 실패하면 0.5초 지연한다. 변경 요청에는 `X-Admin-Request: 1` 헤더가 있어야 한다(다른 사이트에서 만든 요청 차단).
  한계: 지금은 HTTP라서 비밀번호가 암호화되지 않는다(로그인 화면에도 안내). TLS를 붙이면 쿠키에 `Secure`가 자동으로 붙는다.
- **화면**: 상태별 건수(대기·수집 중·완료·실패)와 거르기, 수집기 상태(일하는 중/쉬는 중), 요청 목록(지역 좌표와 지도 링크, 요청 횟수, 주변 카페 수, 수집한 수, 시간, 메모). 수집기가 일하는 동안 10초마다 자동 새로고침. 모바일에서는 카드로 바뀐다.
- **기능**: **지금 실행**(그 요청만 바로 수집) · **대기열로**(실패·완료 요청을 다시 대기열에) · **삭제**(두 번 확인, 수집 중인 요청은 삭제 불가) · 새로고침 · 로그아웃.
- **지금 실행의 동작**: API가 클러스터에 Job `aicafe-collect-now-<id>-<시각>`을 만든다. 야간 CronJob의 정의를 그대로 복사해 인자만 `--request-id <id> --budget-minutes 60`으로 바꾸므로 이미지·Secret·자원 제한이 같다. 수집기가 이미 일하는 중이면(야간 실행 포함) 409로 거절한다 — 두 수집기가 동시에 네이버를 부르면 차단당하기 쉽다. 끝난 Job은 24시간 뒤 자동 삭제된다.
  API 파드의 ServiceAccount `aicafe-api`는 이 네임스페이스에서 Job 생성 · 해당 CronJob 읽기 · 파드 목록만 허용된다(`deploy/k8s/base/admin-rbac.yaml`). 클러스터 밖(로컬 개발)에서는 "지금 실행"이 503으로 거절된다.
- **복구**: 수집기가 죽어서 4시간 넘게 `running`으로 남은 요청은 다음 수집 실행이 시작될 때 대기열로 돌아간다.
- **API**: `POST /api/v1/admin/login|logout` · `GET /api/v1/admin/session` · `GET /api/v1/admin/collection-requests` · `DELETE /api/v1/admin/collection-requests/{id}` · `POST /api/v1/admin/collection-requests/{id}/run|requeue`.

### 6.1 DB 스키마(초안)
- `cafe(place_id PK, name, category, lat, lng, road_address, jibun_address, phone, rating, review_count, micro_review, rank_score, has_booking, business_status, business_status_text, business_hours JSONB, cover_photo_url, photo_urls JSONB, conveniences JSONB, menu_mentions JSONB, content_hash, is_active, first_seen_at, last_seen_at, detail_fetched_at, last_crawled_at)` — 구현됨(마이그레이션 0001). 원본 전체 JSON은 저장하지 않고 파싱한 필드만 저장 + 좌표 인덱스(bbox + 거리 계산; 필요 시 `earthdistance`/PostGIS)
- `cafe_menu(place_id FK, menu_key, name, price, description, image_url, is_signature, mention_count, temp_hint, taste_tags)` — PK(place_id, menu_key)
- `cafe_review(place_id FK, review_key, rating, text_snippet(≤200자), raw_body(임시, 태깅 후 purge), visited_label, ordered_item, photo_url, voted_keywords JSONB, is_noise, taste_tags JSONB)` — 10건만 유지, 노이즈 리뷰의 본문은 저장하지 않음 — PK(place_id, review_key)
- `cafe_taste(place_id PK/FK, taste_vec vector(10), confidence, updated_at)`
- `taste_axis(axis_key PK, label_ko, description)` · `taste_archetype(id PK, name_ko, weather_vec vector(n), taste_vec vector(10), template_hints JSONB)`
- `weather_snapshot(tm PK, fetched_at, stations JSONB)` — 시각 단위 전국 관측 스냅샷(한 번 받으면 재사용) · `kma_station(stn_id PK, name, lat, lng)` — 좌표표(§15)
- `collection_request(id PK, cell_key UNIQUE, lat, lng, radius_m, status, request_count, requested_at, last_requested_at, started_at, finished_at, cafes_found, note)` — 방문자 수집 요청(§6.2, 마이그레이션 0004)
- 모든 벡터 컬럼에 HNSW 인덱스. 마이그레이션은 Alembic.

## 7. 추천 API (FastAPI, 헥사고날)
- `GET /api/v1/recommendations?lat&lng&radius_m=1000` → `{ weather, taste, items:[{rank, cafe, menu, reason, message, distance_m}], more_items:[...] }`
  `items`는 TOP 3(순위 1~3), `more_items`는 그 뒤를 잇는 **추가 10곳**(순위 4~13)이다. 추가 목록은 TOP 3와 같은 점수·반경을 쓰되 ① TOP 3에 오른 브랜드는 빼고 한 브랜드당 1곳, ② 같은 음료 종류가 몰리지 않게 섞고, ③ 영업 중인 곳을 최대 5곳까지 우선해 채운다(심야에 닫은 곳만 보이는 것을 막기 위해, 영업 상태는 여전히 표시만 하고 걸러내지는 않는다). 주변 카페가 적으면 10곳보다 적게 나오고, 없으면 `[]`이다. 문구는 3순위와 같은 톤을 쓴다.
- `GET /api/v1/weather?lat&lng` · `GET /api/v1/cafes/{place_id}` · `GET /healthz`
- `POST|GET /api/v1/collection-requests` — 데이터가 없는 지역의 수집 요청과 진행 상황(§6.2)
- 흐름: 좌표 → 최근접 KMA 관측소(관측소 좌표표 + haversine) → 날씨 벡터 → 입맛 벡터 검색 → 반경 내 후보(DB) → 점수화 → TOP3 → 멘트.
  결과는 `(geohash7, 날씨 버킷)` 키로 10분 캐시. 반경 내 데이터가 부족하면 "이 지역은 아직 준비 중" 상태와 가장 가까운 수집 지역 안내.
- **영업상태 규칙**: 카페는 영업 중/종료를 **표시**하며 필터링하지 않는다(DB에는 수집 시각의 `business_status`와 요일별 영업시간을 저장하고, 응답 시 현재 시각으로 재계산).
  단 TOP3 안에 **영업 중이 2곳 이상**이어야 한다. 점수 순으로 뽑되 영업 중이 2곳 미만이면 영업 중 후보를 점수 순으로 끌어올려 채운다(표시 순위는 점수 순 유지).
  반경 내 영업 중 후보가 2곳 미만이면 반경을 2km → 3km → 5km로 단계 확장하고, 그래도 부족하면 "지금은 영업 중인 곳이 적어요"와 다음 오픈 시각을 안내한다(심야 대비, 실제로 오늘 밤 23시대 표본 6곳 중 5곳이 영업 종료였다).
  영업상태 수집 시각이 오래되었으면(예: 6시간 초과) 영업시간표로 재계산하고 "정보 기준 시각"을 표시한다.
- 위치 좌표는 저장하지 않고 로그에는 geohash 5자리로만 남긴다.

## 8. 멘트 템플릿 (자연스러움 보장)
LLM 자유 생성 대신 **슬롯 기반 템플릿 + 변형 풀**로 생성한다(환각 차단, 지연 없음).
- 슬롯: `{area}` `{weather_phrase}` `{taste_phrase}` `{cafe}` `{menu}` `{evidence}` `{distance}` `{rank_tone}`
- 입맛 아키타입마다 `weather_phrase`/`taste_phrase`/`evidence` 후보 3~5개, 순위별 톤(1위 단정·강조 / 2·3위 간결) 템플릿 각 3~5종.
- **한국어 조사 처리 유틸**(을/를, 이/가, 은/는, 과/와, (으)로)로 받침에 따라 자동 선택. 메뉴·카페명 길이 제한과 예외 처리.
- 근거는 실제 리뷰 태그/문장에서만 인용(없으면 생략). 단정 표현("비 오면 우울") 금지. 후보 금지어/길이 검증 후 출력.
- 톤: **존댓말 + 이모지**(문장당 1개 이내, 날씨·메뉴에 맞는 이모지 사전: ☔🌧️☀️❄️🧊☕🍰 등. 영업 종료 카페는 🌙 표시와 오픈 시각 안내)
- 예시: "비가 부슬부슬 내리는 역삼동이에요 ☔ 오늘은 따뜻하고 고소한 한 잔이 어울려요. **○○커피**의 **헤이즐넛 라떼**는 '고소하다'는 리뷰가 많은 메뉴예요 ☕ (도보 4분, 지금 영업 중이에요)"

## 9. 프론트엔드 (React + FSD, 웹)
- 컨셉: **"오늘의 날씨가 고른 한 잔"** — 날씨에 따라 배경·색·모션이 바뀌는 카페 감성 UI
  (맑음: 크림+시트러스 / 비: 청회색 유리 질감+물방울+따뜻한 조명 / 추움: 에스프레소 브라운+김 / 더움: 민트+얼음 하이라이트, 다크모드 지원).
  타이포는 Pretendard(본문) + 세리프 포인트, 한국어 우선, 모바일 퍼스트.
- 화면: 히어로(현재 날씨·입맛 한 줄) → **TOP3 카드**(순위, 카페명, 메뉴, 입맛 칩, 추천 이유 멘트, 거리, 네이버 지도 열기 링크) → 지도.
- 위치: 브라우저 Geolocation(권한 거부 시 역삼역 기본). **주의: HTTP(TLS 없음)에서는 최신 브라우저가 Geolocation을 차단**(보안 컨텍스트 아님, localhost 제외)하므로
  운영 주소에서는 "현재 위치" 버튼이 동작하지 않는다. 대응: 기본 위치(역삼역)로 시작 + 지도 선택을 1차 수단으로 제공하고, 나중에 TLS가 생기면 자동으로 활성화되게 구현한다. + **지도 핀 이동/탭으로 지역 선택 → "이 지역에서 다시 추천"**.
  지도는 네이버 지도 JS SDK(NCP Maps 클라이언트 ID 필요).
- FSD 슬라이스 예: `pages/home`, `widgets/{weather-hero,recommendation-list,location-map}`, `features/{pick-location,use-geolocation}`,
  `entities/{cafe,weather,taste}`, `shared/{api,config,ui}`. API 주소는 빌드타임 env(`shared/config`).
- 접근성: 대비, 모션 감소 설정 준수, 로딩/빈 상태/오류+재시도/오프라인 처리.

## 10. 배포 아키텍처 (k3s / `aicafe`)
| 구성요소 | 형태 | 리소스(초기) |
|---|---|---|
| postgres-pgvector | StatefulSet(`pgvector/pgvector:pg16` 계열) + PVC(`local-path`), Secret | 1Gi / 15Gi |
| backend (FastAPI) | Deployment 1~2, Service | 512Mi |
| frontend | Deployment(nginx 정적 서빙) + Service | 64Mi |
| crawler | Job/CronJob(백엔드 이미지, CLI) | 256Mi |
| ingress | **Traefik** (`ingressClassName: traefik`, 표준 Ingress 사용). 외부 노출용 Service 필요(§10.1). 호스트 `rcafe.koh.it.kr`, TLS 없음(`web` entryPoint만 사용) | – |
### 10.1 Traefik 상태 (kubectl 읽기 전용, 2026-10-09 재확인)
- 사용자가 ingress-nginx를 제거해 `ingress-nginx` 네임스페이스는 비었고, 외부 IP(121.143.126.21)의 80/443을 잡고 있던 Service도 없다.
- 그러나 Traefik 파드(`kube-system`)는 실행 중이지만 **`traefik` Service가 없다**(클러스터 전체 Service 목록에 없음). 따라서 지금은 어떤 Ingress도 외부에서 도달할 수 없다.
- 해야 할 일(M5): `kube-system`에 Traefik Service(80→web, 443→websecure; k3s ServiceLB 또는 externalIP 121.143.126.21)를 만든다.
  **kube-system 변경이라 `kubectl diff` 결과를 보여드리고 승인받은 뒤 적용**한다. 실제 포트 매핑은 Traefik 파드의 entryPoint 설정(컨테이너 포트 8000/8443 vs 인자 :80/:443)을 확인해 결정한다.
- 영향 고지: 기존 `chf`, `chn` Ingress는 `ingressClassName: nginx`라서 nginx 제거 후에는 동작하지 않는다. 이 프로젝트에서는 건드리지 않는다(필요하면 Traefik 클래스로 옮기는 작업을 따로 제안).
- 시크릿(KMA 키, DB 비밀번호)은 K8s Secret으로만 주입. 매니페스트는 `deploy/k8s/`(Kustomize base+overlay) 에 두고
  `kubectl --context charles-k3s -n aicafe diff` → 사용자 승인 후 `apply`.
- 기존 `terraform-deploy`/`deploy-frontend` 스킬은 AWS(S3/CloudFront) 전용이라 k3s에는 맞지 않는다 →
  **`deploy-k3s` 스킬 신규 작성**(컨텍스트·네임스페이스 고정, diff→승인→apply, 다른 컨텍스트 거부).
- 메모리 예산: 노드 여유 약 9GB. Postgres 1 + backend 0.5 + frontend 0.1 → 여유 충분.

## 11. 저장소 구조와 품질 게이트
```
backend/app/{domain,application,adapters/{inbound/{http,cli},outbound/{persistence,clients}}}/ , main.py   # clients: naver, kma
frontend/src/{app,pages,widgets,features,entities,shared}
deploy/k8s/{base,overlays/prod}   docs/{PRD.md,evidence.md}
```
- `setup-quality-gates` 스킬로 backend(ruff/mypy strict/import-linter), frontend(Steiger/ESLint/tsc) 게이트 구성.
- 도메인은 프레임워크·DB·HTTP를 모르고, 네이버/KMA/pgvector는 포트 뒤 어댑터로 둔다(테스트는 인메모리 페이크).

## 12. 마일스톤
- **M0 조사 스파이크 — 완료(2026-10-09)**: 네이버 상세 수집 가능·스키마, KMA 형식·결측, Traefik 상태 확인. 남은 항목: 근거 문헌 원문 확인, KMA 관측소 좌표표(§15).
- **M1 데이터 — 진행 중**: DB 스키마·크롤러·upsert 완료(테스트 25건, ruff/mypy strict/import-linter 통과). 로컬 DB에 카페 314곳(기본 정보), 상세 71곳 적재.
  1초당 1요청 속도에서 네이버가 400/429로 제한해 크롤이 중단됨 → 검색 2초·상세 3초 간격 + 연속 실패 시 중단(서킷 브레이커)으로 변경. 남은 일: 쿨다운 후 재개, 클러스터 DB 배포(승인 후).
- **M2 입맛 — 구현 완료(규칙 사전 기반)**: 입맛 축 10개, 키워드 사전 태깅, 카페 입맛 벡터, 날씨 시나리오 306개 시드, pgvector 유사도 검색, `preview` 명령으로 날씨별 카페·메뉴 확인. 자세한 내용은 `docs/taste-model.md`. 수기 라벨 120건 평가 완료, 전체 카페 재계산 완료. 로컬 LLM 태깅은 시험 후 폐기.
- **M3 API/멘트 — 구현 완료**: 추천 API(`/api/v1/recommendations`, `/api/v1/weather`), 점수화(§5.4), 영업 중 2곳 이상 규칙과 반경 확장, 브랜드 중복 제한, KMA 연동(시간별 스냅샷 재사용), 멘트 템플릿(존댓말+이모지, 조사 처리, 검증), 한국 시간대 처리. 테스트 88건. 미완: 멘트 평가셋(사람 평가), 관측소 공식 좌표표, 서울 외 지역.
- **M4 웹 — 완료**: React + Vite + FSD. 날씨(비·더위·추위·선선)와 시간대(낮/저녁)에 따라 색·모션이 바뀌는 테마, 오늘의 입맛 칩, TOP3 카드(사진·메뉴·가격·영업 상태·멘트·네이버 지도 링크), Leaflet+OSM 지도(눌러서/핀을 끌어서 지역 선택, "이 위치에서 다시 추천받기"), 역 바로가기 4곳(M9에서 삭제 가능한 즐겨찾기로 바뀜), URL로 지역 공유. TLS가 없어 "내 위치"는 브라우저가 막으므로 비활성+안내. 테스트 28건, eslint·tsc·steiger 통과.
- **M5 배포 — 완료**: `deploy-k3s` 스킬, kustomize 매니페스트(Postgres+pgvector, backend(마이그레이션 init), frontend(nginx), Traefik IngressRoute), 이미지는 서버의 기존 레지스트리(`121.143.126.21:5000`, amd64). 사용자 승인으로 kube-system에 `traefik` Service 추가. 남은 leftover(ingress-nginx 검증 웹훅)가 모든 Ingress를 막아 IngressRoute를 사용.
- **M9 즐겨찾기 지역 — 완료**: 기본 4곳(역삼·강남·선릉·논현역)은 처음 방문 때 채워지는 **삭제할 수 있는 즐겨찾기**가 되었고, 지금 보는 지역에 이름을 붙여 추가할 수 있다(최대 20곳, 이름 20자, 15m 안의 같은 위치는 중복 불가). 계정이 없으므로 **이 브라우저의 localStorage**(`rcafe.favorites.v1`)에만 저장되어 기기·브라우저마다 따로이고, 서버로 보내지 않는다. 삭제는 `편집` 모드에서만 ✕가 나타나 오탭을 막고, 전부 지워도 빈 목록이 유지되며 `기본 지역 되돌리기`로 복원한다. 상단 "○○ 주변" 이름은 즐겨찾기 이름을 먼저 쓰고, 삭제한 역도 지명은 그대로 보여 준다. 다른 탭의 변경은 `storage` 이벤트로 따라가고, 저장소가 막힌 브라우저에서는 그 방문 동안만 유지된다. 테스트 frontend 79건.
- **M8 추천 더보기 — 완료**: TOP 3 아래 "추천 더보기 · 10곳" 버튼. 기본은 접혀 있고(추가 목록은 화면에 그리지도, 사진을 불러오지도 않는다) 누르면 컴팩트 카드 10장이 펼쳐지며 목록 끝과 위쪽 버튼으로 다시 접는다. 지역을 바꾸면 다시 접힌다. 테스트 backend 172건 · frontend 56건.
- **M7 관리자 페이지 — 완료**: `/admin` 로그인(서명 쿠키), 수집 요청 목록·거르기·삭제·대기열로·지금 실행(클러스터 Job), 정체된 `running` 자동 복구, RBAC 최소 권한. 테스트 backend 164건 · frontend 49건.
- **M6 방문자 수집 요청 — 완료**: 빈 지역 화면의 "이 지역 수집 요청하기" 버튼, 접수 API(셀 단위 병합·방문자별 제한·대기열/일일 상한), 새벽 03:30 KST CronJob 수집기(시간 예산·중단 후 재개·차단 시 즉시 중단·새 카페만 입맛 계산). 테스트 backend 139건 · frontend 38건.

## 13. 검증 방법
- 단위: 도메인(점수화·조사·템플릿) 인메모리 페이크 테스트, 크롤러 upsert 멱등성(같은 데이터 2회 적재 → 행 수 불변·`last_crawled_at`만 갱신).
- 데이터: 역삼 커버리지(알려진 카페 샘플 30곳 중 포함률 ≥ 90%), 입맛 태깅 F1.
- 추천: 날씨 시나리오 6종(무더위/한파/비/맑음/흐림/눈) 고정 입력 → 입맛·TOP3·멘트 스냅샷 리뷰.
- E2E: 로컬 `docker compose` 또는 kind 대체 없이 k3s `aicafe`에 배포 후 `curl /api/v1/recommendations?...`, 브라우저에서 위치 변경·지도 선택 확인.

## 14. 리스크
- 네이버 비공식 API: 약관·차단·스키마 변경 → 저속 수집, 원본 보관, 어댑터 격리, 상용화 전 공식 제휴/API 재검토.
- 리뷰 원문 저작권·개인정보 → 파생 태그 위주 저장, 짧은 근거 문장만 보관, 작성자 정보 미수집.
- 날씨–입맛 근거가 약함 → 휴리스틱임을 명시, 가중치 설정화, 단정 멘트 금지.
- 로컬 모델 성능(CPU) → 시험해 본 뒤 LLM을 쓰지 않기로 하고 삭제했다.
- 단일 노드 용량/가용성 → 리소스 상한 설정, PVC 백업(pg_dump CronJob) 검토.
- KMA API 키가 대화에 노출됨 → 키는 Secret으로만 사용, 노출이 우려되면 재발급 권장.

## 15. 남은 일 (선택 사항)
서비스는 동작 중이며, 아래는 품질을 더 올리기 위한 후속 작업이다.
1. **TLS(HTTPS)**: 지금은 HTTP라서 브라우저가 "내 위치"를 막는다. 인증서(cert-manager 또는 수동)를 붙이면 `내 위치` 버튼이 자동으로 켜진다(코드 변경 없음, Traefik `websecure` 라우트만 추가).
2. **네이버 지도 SDK**: NCP Maps 클라이언트 ID가 생기면 `widgets/location-map`의 Leaflet을 네이버 지도로 교체한다.
3. **KMA 관측소 좌표표**: 현재 수도권 8곳의 근사 좌표(`backend/data/kma_stations.csv`)만 쓴다. `stn_inf` 권한을 신청하거나 공식 목록을 받으면 교체해 전국으로 넓힌다.
4. (종료) **로컬 LLM**: Ollama(`qwen3:4b`, `qwen3:1.7b`)를 k3s에 설치해 시험했고 사전보다 부정확하고 느려서(1.7b F1 0.33 vs 사전 0.71, 리뷰당 약 13초) 사용자 요청으로 클러스터에서 모두 삭제했다. 다시 쓰려면 GPU가 있는 환경이 필요하다.
5. **데이터 확장·갱신**: 역삼 외 지역은 방문자 수집 요청(§6.2)으로 새벽에 자동 수집한다. 직접 하려면 `discover --lat --lng`와 `deploy/k8s/jobs/job.yaml`을 쓴다. 영업 상태는 수집 시각이 오래되면 영업시간표로 계산한다.
   한계: 기상청 관측소 좌표가 수도권뿐이라 관측소에서 40km 넘게 떨어진 지역은 날씨 오류(503)가 먼저 나서 수집 요청 버튼까지 가지 못한다(3번을 풀어야 전국으로 넓어진다).
6. **멘트 평가**: 사람이 멘트 20건을 보고 자연스러움을 평가하는 절차(§1 성공 기준)는 아직 하지 않았다.
7. (완료) 클러스터에 남아 있던 ingress-nginx 검증 웹훅(`ingress-nginx-admission`)은 사용자 요청으로 삭제했다. 새 Ingress도 다시 만들어진다.

## 16. 최종 상태 (2026-10-10)
- 수집: 역삼역 반경 2km, 카페 380곳 · 메뉴 9,771개 · 리뷰 3,739건(원문 삭제, 태그·200자 요약만 보관).
- 서비스: http://rcafe.koh.it.kr (Traefik → nginx → FastAPI → Postgres+pgvector), 기상청 실시간 관측 사용.
- 품질: backend 172 tests + ruff + mypy strict + import-linter, frontend 79 tests + eslint + tsc + steiger. 입맛 사전은 손 라벨 120건으로 평가(실제 리뷰 요약 기준 블라인드 세트 F1 0.74 → 0.82; 저장소의 테스트 세트는 가상 문장이다. `docs/taste-model.md`).
