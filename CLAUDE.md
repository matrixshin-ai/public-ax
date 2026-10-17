# CLAUDE.md — public-ax

## 프로젝트 개요

- 울산 산업 AX 공개 앵커 인덱스. 원천 흐름: `korea-industry-ax` 웹앱 수록 기사 →
  (Obsidian export) → `ax-vault-full`(private archive) → (공개 가능 필드만 재색인) → `public-ax`.
- `ax-vault`(구 public summary vault)는 2026-10-10 폐기(private + archive). **사용하지 말 것.**
- 공개 기준은 `docs/public_anchor_policy.md`, 갱신 절차는 `docs/anchor_update_procedure.md`.

## 금지·원칙

- 기사 전문·본문 일부·긴 인용 금지. 요약은 1~3문장의 짧은 사실 요약만.
- 코드·문서에 개인 로컬 경로를 쓰지 않는다. 원자료 경로는 `--source` 또는 `AX_VAULT_SOURCE`.
- **자동 공개(2026-10-17~).** GitHub Actions `auto-publish.yml`이 매일 KST 12:30에 사람 승인 없이
  후보 추출 → 요약 생성 → 안전성 검사 → 통과분만 `master`에 직접 commit·push한다.
  공개 조건: 요약 존재 + COPY_RUN 없음 + 유출 검사 통과. 상세는 아래 "자동 공개".
  수동 스크립트 절차(`docs/anchor_update_procedure.md`)는 예비용이며, 로컬에서 수동 commit/push는 사용자 확인 후에만.
- **공개 로그 규칙.** public-ax는 공개 저장소라 Actions 로그·커밋 메시지·Issue가 모두 공개된다.
  기사 본문, 원문 일치 문장, 요약·관련성 원문, 제목·URL은 절대 출력하지 않는다. 안전성 검사
  결과도 앵커 ID와 사유 코드만. `tests/test_auto_publish_logs.py`가 검증하며 CI에서 공개 전에 돈다.
  스크립트 출력을 바꾸면 이 테스트를 같이 고친다.
- history rewrite·force push 금지.

## 스크립트

| 파일 | 역할 |
|---|---|
| `scripts/dry_run_select_anchors.py` | 후보 분류(A/B1/B2/C/D)·scope, 공용 헬퍼(`--since`/`--date`/`--include-published`, 공개된 앵커 ID 수집) |
| `scripts/generate_direct_anchor_summaries.py` | Claude API로 요약·관련성 생성 → `_work/direct_anchor_summaries_preview.json`(누적, git 제외) |
| `scripts/export_direct_anchors.py` | daily 생성·덧붙이기, `index.md`·`README.md` 갱신, `--retag` |
| `scripts/anchor_safety.py` | 원문 50자 연속 복사, 템플릿 외 줄, private 경로 형식, 로컬 경로, review 메모, `[미작성]` 검사. `*_issues`는 사유 코드 포함 |
| `scripts/auto_publish.py` | 자동 공개 본체(CI 전용). 앵커별 판정, 품질 보정, ID·코드만 출력, 결과 JSON·커밋 메시지 생성 |
| `scripts/auto_publish_github.py` | `hold`(새 보류 ID Issue, 열린 Issue와 중복 제외) / `weekly`(주간 요약 Issue) |
| `scripts/unpublish_anchor.py` | 공개 앵커 하나 내리기: 블록 제거 → 번호·anchor_count·index·README 재계산 → exclude 등록 |
| `config/auto_publish_exclude.txt` | 공개 철회 ID. 자동·수동 갱신 모두 다시 고르지 않음 |

- 분류: A=울산 직접(제목 울산/UNIST/울산대, region=울산, ulsan_score>0), B1=제목 산업·기업
  키워드 또는 core=1(단 region=타지자체 제외), B2=industries만 일치, C=AX 기술, D=기타.
  scope: direct=A, direct-plus=A+B1, topics=C, all.
- 요약 모델: `--model` > `AX_SUMMARY_MODEL` > 기본 `claude-sonnet-5`. CI에서는 저장소 Variable `AX_SUMMARY_MODEL`.

## 자동 공개

- 워크플로: `.github/workflows/auto-publish.yml`(매일 03:30 UTC = KST 12:30, `workflow_dispatch`,
  concurrency `public-ax-publish`), `auto-publish-weekly.yml`(월 06:00 UTC = KST 15:00).
  12:30인 이유: korea-industry-ax export가 늦으면 KST 11:53경 끝난 날이 있음(10-13). export 도중이나
  직전(대략 KST 08:50~12:00)에 수동 실행하면 vault 삭제와 엇갈릴 수 있다(10-17 `690b32fa` 사례).
- 인증: ax-vault-full 읽기 전용 deploy key → Secret `AX_VAULT_FULL_READ_KEY`. Claude API → Secret `ANTHROPIC_API_KEY`.
- 후보 범위: 마지막 공개 날짜 − 7일 이후, 공개된 ID·exclude 제외. 보류 앵커는 이 기간 동안 매일 재시도.
- **COPY_RUN 기준 50자 (summary·관련성 모두).** 이유: AX 기사는 영문 약어 + 풀이 + 한국어 대응어
  조합이 많아 고유명칭만으로 40자를 넘는 경우가 많다. 3회 재생성 후에도 걸리면 보류.
- 보류(공개 안 함): `SUMMARY_API_ERROR`·`SUMMARY_REFUSAL`·`SUMMARY_TRUNCATED`·`SUMMARY_PARSE`·`SUMMARY_EMPTY`,
  `COPY_RUN`, `FIRST_SENTENCE_TOO_LONG`(첫 문장만으로 200자/100자 초과), `TEMPLATE_LINE`, `LOCAL_PATH`,
  `REVIEW_NOTE_LEAK`, `PENDING_LEFT`, `PRIVATE_PATH_FORMAT`, `FILE_CHECK_FAILED`(파일 검사 실패 시 그 파일의 신규 앵커만).
- 품질 보정 후 공개(주간 요약에 ID·코드 표시): `TOO_LONG`·`TOO_MANY_SENTENCES`(문장 단위로 자름),
  `RELEVANCE_LABEL`("울산 정책 참고사례"로 보정). 요약·관련성의 줄바꿈은 검사 전에 한 칸으로 정리.
- **원본 소멸 자동 내림.** 실행마다 공개된 앵커의 vault 파일(파일명 끝 anchor_id 기준)이 있는지 본다.
  없으면 블록을 내리고 exclude에 `# unpublished <날짜> SOURCE_VANISHED`로 등록한다. vault 파일은
  korea-industry-ax `export_to_vault.py`가 그 기사를 다른 기사의 `related`로 흡수했을 때만 지운다
  (수집 기간에서 빠진 기사는 지우지 않음). 대표 기사는 보통 다음 실행에서 따로 공개된다.
  한 번에 **5건 넘게** 사라졌으면 vault 체크아웃 이상으로 보고 아무것도 내리지 않고(요약 생성도 안 함)
  실패 처리 → 실패 Issue 제목·본문에 `VANISHED_TOO_MANY`와 건수.
- 커밋: 실행 1회당 1개. 제목 `auto-publish YYYY-MM-DD: N anchors[, M unpublished]`, 본문
  `- <id> daily/<날짜>.md [quality: ...]` / `- unpublish <id> daily/<날짜>.md (SOURCE_VANISHED)`.
  공개·내림 모두 0건이면 커밋 안 함. 작성자 github-actions[bot].
- 알림(Issue): 새 보류 ID가 있으면 `auto-publish-hold`(열린 hold Issue에 이미 있는 ID는 제외),
  실행 실패 시 `auto-publish-failure`(사유 코드가 있으면 함께), 주간 요약 `auto-publish-weekly`
  (공개·품질 보정·보류·"원본 소멸로 내림: ID"·실행 실패).
- 앵커 내리기: `python scripts/unpublish_anchor.py <id>`(dry-run) → `--write` → git diff 확인 → commit/push.
  exclude에 등록되므로 다음 자동 실행이 다시 공개하지 않는다. 보류 Issue의 앵커를 영구히 빼려면
  exclude 파일에 ID만 추가한다. `git revert`만 하면 다음 날 다시 공개되니 쓰지 않는다.

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

### 2026-10-17 — 완전 자동화
- 수동 승인형 → GitHub Actions 자동 공개로 전환(위 "자동 공개"). 10-10 이후 미공개 direct 후보 83건이 첫 대상.
- COPY_RUN 30자 → 50자. 기존 review 3건(45a4a523·9780a07a는 COPY 31·30자, 5279bc43은 3문장)은
  새 기준이면 각각 통과 / 품질 보정 대상. 이미 공개된 69건은 다시 처리하지 않음.
- 실제 daily 69건 전부에 블록 제거를 돌려 다른 블록·헤더가 바뀌지 않음을 확인(unpublish_anchor.py).
- 첫 실행(workflow_dispatch, run 38983725995): 83건 공개·보류 0(`7b0ca87`) → 152건. 원문 최장 일치 42자.
  로그에서 제목·요약·관련성·URL 0건 확인(본문 조각 일치 18건은 전부 pytest 출력의 공백 15칸 오탐).
- `690b32fa` 내림(`f8f4208`): 실행이 vault를 받은 23:52 UTC 직후 23:54 UTC export에서 대표 기사
  `8e3e7880`(A그룹, 미공개)의 related로 병합돼 vault 파일이 지워짐. 대표 기사는 다음 실행에서 공개 대상.
  → 재발 대비로 원본 소멸 자동 내림 추가, 정기 실행을 KST 12:30으로 변경.

## 남은 일

- 다음 정기 실행에서 `8e3e7880` 공개 확인.
- 첫 주간 요약(2026-10-19 월) Issue 내용 확인.
- export-summary가 다음 자동 실행에서 skipped로 나오는지(korea-industry-ax 쪽) 확인.
