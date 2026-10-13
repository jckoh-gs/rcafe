# aicafe — 날씨가 고른 카페

지금 위치의 날씨로 "오늘 어울리는 입맛"을 정하고, 가까운 카페와 메뉴를 3곳 추천하는 웹 서비스입니다.
운영 주소: <http://rcafe.koh.it.kr> (TLS 없음 → 브라우저가 "내 위치"를 막으므로 지도와 즐겨찾기 지역 버튼으로 지역을 고릅니다. 즐겨찾기는 이 브라우저에만 저장됩니다)

| 폴더 | 내용 |
|---|---|
| `backend/` | FastAPI(헥사고날) API, 네이버 수집기(CLI), 입맛 모델, KMA 날씨 연동 — [README](backend/README.md) |
| `frontend/` | React + Vite + FSD 웹. 날씨 테마 UI, Leaflet(OSM) 지도 |
| `deploy/k8s/` | k3s 매니페스트(kustomize): Postgres+pgvector, backend, frontend, IngressRoute(Traefik), 1회성 Job |
| `docs/` | [PRD](docs/PRD.md) · [입맛 모델](docs/taste-model.md) · [근거 자료](docs/evidence.md) |
| `.claude/` | 프로젝트 룰, 품질 게이트 훅, 배포 스킬(`deploy-k3s`) |

## 동작 흐름
1. 수집(오프라인): 네이버 지도 검색 → 장소 ID로 upsert → 상세 페이지(메뉴·영업시간·리뷰 10건) → 입맛 태그 → 카페별 입맛 벡터.
   데이터가 없는 지역은 방문자가 "이 지역 수집 요청하기"로 요청하면 큐에 쌓이고, 새벽 03:30(KST) CronJob이 모아서 수집합니다.
   운영자는 `/admin`(로그인 필요)에서 요청을 보고, 지금 실행하거나 삭제할 수 있습니다.
2. 요청: 좌표 → 가장 가까운 기상청 관측소의 시간별 관측(시간당 1회만 호출·재사용) → 날씨 벡터 → pgvector 유사도 검색으로 원하는 입맛 →
   점수화(입맛·평점·거리·메뉴) → 영업 중 2곳 이상 보장 → 멘트 템플릿.

## 로컬 개발
```bash
docker compose -f docker-compose.dev.yml up -d                    # pgvector Postgres (localhost:55432)
cd backend && uv sync && uv run alembic upgrade head && uv run pytest
AICAFE_KMA_AUTH_KEY=... uv run uvicorn app.main:app --port 8010   # API
cd ../frontend && npm install && npm run dev                      # http://localhost:5173 (/api -> :8010)
```
품질 게이트: backend `ruff` · `mypy --strict` · `import-linter` · `pytest`, frontend `eslint` · `tsc` · `steiger` · `vitest`.

## 배포 (k3s, context `charles-k3s`, namespace `aicafe`)
`.claude/skills/deploy-k3s/SKILL.md` 참고. 요약: `deploy.sh check|secrets|build <tag>|diff <tag>|apply <tag> --yes|load-data|job|smoke`.
이미지는 서버에 이미 있는 레지스트리(`121.143.126.21:5000`)에 amd64로 푸시합니다. 비밀(KMA 키, DB 비밀번호)은 K8s Secret으로만 주입하며 저장소에 두지 않습니다.

## 데이터와 정책
- 네이버 비공식 내부 API를 개인/PoC 용도로 낮은 속도(검색 약 2초, 상세 약 3초에 1회)로 수집합니다. 상용 전환 전에 재검토가 필요합니다.
- 리뷰는 입맛 태그와 200자 이내 요약만 보관합니다(원문은 태깅 후 삭제). 위치 좌표는 저장하지 않습니다.
- 날씨와 입맛의 관계는 연구 결과가 약하고 엇갈려서 휴리스틱으로만 사용합니다([근거](docs/evidence.md)).
