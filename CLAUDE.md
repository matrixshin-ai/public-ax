# CLAUDE.md — public-ax

## 프로젝트 개요

- 울산 산업 AX 공개 앵커 인덱스. 원천 흐름: `korea-industry-ax` 웹앱 수록 기사 →
  (Obsidian export) → `ax-vault-full`(private archive) → (공개 가능 필드만 재색인) → `public-ax`.
- `ax-vault`(구 public summary vault)는 2026-10-10 폐기(private + archive). **사용하지 말 것.**
- 공개 기준은 `docs/public_anchor_policy.md`, 갱신 절차는 `docs/anchor_update_procedure.md`.

## 금지·원칙

- 기사 전문·본문 일부·긴 인용 금지. 요약은 1~3문장의 짧은 사실 요약만.
- 코드·문서에 개인 로컬 경로를 쓰지 않는다. 원자료 경로는 `--source` 또는 `AX_VAULT_SOURCE`.
- **자동 반영 없음.** 후보 추출 → 검토 → 요약 preview → 품질 검사 → `--write` → commit/push
  모든 단계를 사람이 확인한 뒤 진행. commit/push는 사용자 확인 후에만.
- history rewrite·force push 금지.

## 스크립트

| 파일 | 역할 |
|---|---|
| `scripts/dry_run_select_anchors.py` | 후보 분류(A/B1/B2/C/D)·scope, 공용 헬퍼(`--since`/`--date`/`--include-published`, 공개된 앵커 ID 수집) |
| `scripts/generate_direct_anchor_summaries.py` | Claude API로 요약·관련성 생성 → `_work/direct_anchor_summaries_preview.json`(누적, git 제외) |
| `scripts/export_direct_anchors.py` | daily 생성·덧붙이기, `index.md`·`README.md` 갱신, `--retag` |
| `scripts/anchor_safety.py` | 원문 30자 연속 복사, 템플릿 외 줄, private 경로 형식, 로컬 경로, review 메모, `[미작성]` 검사 |

- 분류: A=울산 직접(제목 울산/UNIST/울산대, region=울산, ulsan_score>0), B1=제목 산업·기업
  키워드 또는 core=1(단 region=타지자체 제외), B2=industries만 일치, C=AX 기술, D=기타.
  scope: direct=A, direct-plus=A+B1, topics=C, all.
- 요약 모델: `--model` > `AX_SUMMARY_MODEL` > 기본 `claude-sonnet-5`.

## 작업 경위

### 2026-10-09
- 저장소 생성(`774f362`): README·index·정책·템플릿 골격. 기사 샘플은 넣지 않음.
- 원천 시스템 흐름 문서화(`3305183`).
- `ax-vault-full` 구조·frontmatter 점검(제목·URL·본문 미출력, 읽기 전용).
- 구 `ax-vault` 폐기: 로컬 폴더 이름 변경, GitHub private 전환 + archive(삭제 안 함).

### 2026-10-10 (새벽) — 초기 구축
- korea-industry-ax `bd5e9dd`: export-summary 비활성화, vault frontmatter에
  region/loc/ulsan_score/core/tech/evidence 추가(이 저장소의 울산 판정 근거).
- dry-run 선택기(`450bf82`) → 개인 경로 제거·환경변수화(`a31d57a`) → exporter(`99ffa04`) →
  요약 생성기(`103b5c9`) → 요약 연동(`74cb365`) → 초기 daily 12개·67건(`1523d9d`) → index(`3b596d5`).

### 2026-10-10 (오후) — 증분 갱신·품질 보강
- export 끊김 의심 점검: 끊김 없음 확인(상세는 korea-industry-ax CLAUDE.md). 재발 방지로
  korea-industry-ax에 export 감시 워크플로 추가(`5a1d880`, 2 수집일 연속 0건·실패 시 Issue).
- 증분 갱신 흐름(`8ce506f`): 공개된 앵커 기본 제외, preview 누적 저장, 같은 날짜 파일 덧붙이기,
  `--accept-review`/`--print-preview`, 쓰기 전 안전 검사, 절차 문서.
- 요약 모델을 `claude-sonnet-5`로 변경하고 `AX_SUMMARY_MODEL` 지원.
- 10-09(`361883e1`)·10-10(`bb2eefb8`) 앵커 추가(`804cee5`) → 14개 파일·69건.
- B1에서 region=타지자체 제외, 태그 키워드에 AI대전환·중소기업 추가(동의어 별칭 포함)(`da374ca`).
  `361883e1`의 industry가 "기타"인 것은 웹앱 고정 산업 14종에 일반 제조·중소기업 항목이
  없어서이며 버그 아님 → 태그로 보완.
- `--retag` 추가 및 기존 7건 태그 갱신(`6c107a9`): git diff로 태그 줄 9줄 추가 외 변경 0줄,
  재실행 시 변경 0건 확인.

### 이 과정에서 고친 문제
- 로컬 경로 검사가 `https://`의 `s:/`를 오탐 → 앞 글자가 영문이면 제외하도록 수정.
- 요약 생성기가 새 앵커만 돌리면 기존 preview를 덮어쓰던 구조 → 누적 저장으로 변경.
- `--accept-review`한 앵커가 복사 검사에서 여전히 막힘 → 이번에 추가될 앵커만 검사, 승인분 제외.
- 새로 만든 파일을 "덧붙임"으로 보고(쓰기 후 판정) → 쓰기 전 상태 기준으로 보고.

## 남은 일

- 월요일(2026-10-12) export 후 `--since 2026-10-10`으로 실행 → 10-10 파일에 첫 실제 덧붙이기.
- export-summary가 다음 자동 실행에서 skipped로 나오는지(korea-industry-ax 쪽) 확인.
