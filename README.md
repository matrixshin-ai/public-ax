# public-ax

울산 산업 AX(AI 전환) 관련 **공개용 앵커 인덱스** 저장소입니다.

## 개요

- 이 저장소는 [korea-industry-ax](https://korea-industry-ax.vercel.app) 웹앱에 수록된 기사 중 **Q&A와 정책분석에 필요한 공개 가능한 앵커만 재색인**합니다.
- `ax-vault-full` 전체를 공개하는 저장소가 아닙니다. 원자료는 비공개 archive인 **`ax-vault-full`** 에 보관되며, 이 저장소에는 기사 전문이 들어가지 않습니다.
- ChatGPT Q&A가 GitHub에서 먼저 검색할 수 있는 **공개 검색지도** 역할을 합니다.
- 운영 현황: 초기 direct daily anchors 12 files, 67 anchors (2026-09-25 ~ 2026-10-08) — [일자별 앵커 목록](index.md#일자별-앵커)

## 원천 시스템

| 구분 | 이름 | 공개 여부 | 역할 |
|---|---|---|---|
| 원천 웹앱 | `korea-industry-ax.vercel.app` | 공개 | 산업 AX 기사 수집·수록 |
| private archive | `ax-vault-full` | 비공개 | 웹앱 수록 기사를 Obsidian으로 export한 원자료 보관소 |
| public anchor index | `public-ax` (이 저장소) | 공개 | 공개 가능한 앵커만 재색인한 검색지도 |

흐름: `korea-industry-ax` → (Obsidian export) → `ax-vault-full` → (공개 가능 필드만 재색인) → `public-ax`

## 저장하는 항목

- 기사 제목
- 언론사명
- 날짜
- 원문 URL
- 짧은 사실 요약 (1~3문장 이하)
- 키워드
- 울산 AX 정책 관련성
- private 원문 위치 (`ax-vault-full` 내부 경로)

## 저장하지 않는 항목

- 기사 전문
- 긴 인용
- 유료기사를 대체할 수준의 상세 요약
- 내부 메모
- 개인정보
- 비공개 업무자료

자세한 기준은 [docs/public_anchor_policy.md](docs/public_anchor_policy.md)를 따릅니다.

## 활용 방식

- ChatGPT Q&A는 이 저장소를 **검색 출발점**으로 사용합니다.
- 앵커에서 관련 기사·주제·기관을 찾은 뒤, 필요하면 앵커의 **URL과 키워드를 바탕으로 인터넷에서 해당 기사와 관련 정부·기업 자료를 다시 확인**합니다.
- 이 저장소의 요약만으로 사실을 단정하지 않고, 원문 URL로 확인하는 것을 원칙으로 합니다.

## 구조

목차는 [index.md](index.md)를 참고하세요.
