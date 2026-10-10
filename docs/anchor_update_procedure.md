# 신규 앵커 갱신 절차 (수동 승인형)

`ax-vault-full`에 새로 들어온 기사 중 울산 직접 관련(scope: direct) 기사를 골라 public-ax daily 앵커로 추가하는 절차입니다.
**자동 반영은 하지 않습니다.** 각 단계의 결과를 사람이 확인한 뒤 다음 단계로 넘어갑니다.

## 준비

- `ax-vault-full`을 최신으로 받습니다: `git -C <ax-vault-full 경로> pull`
- 원자료 경로를 환경변수로 지정합니다 (코드와 문서에는 실제 경로를 쓰지 않습니다).

```powershell
$env:AX_VAULT_SOURCE = "C:\path\to\ax-vault-full\AX뉴스"
```

- 언제 돌리나: korea-industry-ax의 월~토 아침 export가 끝난 뒤(대략 KST 10:30 이후).
  당일 폴더는 그날 06:30 KST까지 게시분만 들어 있으므로, 다음 실행 때 같은 날짜 파일에 덧붙여집니다.

## 단계

| 단계 | 명령 | 쓰는 파일 | 확인할 것 |
|---|---|---|---|
| 1. 후보 추출 | `python scripts/dry_run_select_anchors.py --since YYYY-MM-DD` | 없음 | 신규 후보 수, 이미 공개돼 제외된 수, 날짜별 분포 |
| 2. 후보 검토 | `python scripts/export_direct_anchors.py --since YYYY-MM-DD --allow-missing-summaries` | 없음 | 파일별 계획(새로 만듦 / 덧붙임), 반영 후 합계 |
| 3. 요약 preview | `python scripts/generate_direct_anchor_summaries.py --since YYYY-MM-DD` | `_work/` (git 제외) | 통과 / 검토 필요 / 실패 건수 |
| 4. 품질 검증 | `python scripts/export_direct_anchors.py --since YYYY-MM-DD --print-preview` | 없음 | 9번 "쓰기 전 검사"가 통과인지, 요약 문장을 직접 읽어 보기 |
| 5. daily 생성·덧붙이기 + index 갱신 | 4번 명령에 `--write` 추가 | `daily/`, `index.md`, `README.md` | "쓰기 완료" 메시지 |
| 6. commit / push | `git diff`로 확인 후 직접 실행 | — | daily·index·README만 바뀌었는지 |

- 3단계는 Claude API를 호출하므로 `ANTHROPIC_API_KEY`가 필요하고 비용이 듭니다.
- 요약 모델 기본값은 `claude-sonnet-5`입니다. 코드 수정 없이 바꾸려면 환경변수를 씁니다
  (우선순위: `--model` > `AX_SUMMARY_MODEL` > 기본값).

```powershell
$env:AX_SUMMARY_MODEL = "claude-sonnet-5-5"   # 예: 다른 모델로 바꿀 때
```
- `--date YYYY-MM-DD`를 쓰면 그 날짜만 처리합니다.
- 태그 규칙을 바꾼 뒤 이미 공개된 앵커에도 반영하려면 `python scripts/export_direct_anchors.py --retag`로 바뀌는 tags를 확인하고, `--write`를 붙여 반영합니다 (tags 줄만 바뀌며, 다른 줄이 달라지면 중단).

## 스크립트가 막는 것

5단계 `--write`는 아래 중 하나라도 있으면 **아무 파일도 쓰지 않고 중단**합니다. dry-run에서도 같은 검사 결과를 보여 줍니다.

| 중단 조건 | 해결 방법 |
|---|---|
| 요약이 없는 anchor | 3단계를 같은 `--since`/`--date`로 실행 |
| 요약·관련성이 빈 값 | 3단계를 `--regenerate`로 다시 실행 |
| preview에 review(검토 필요)가 남은 anchor | 문장을 읽어 보고 괜찮으면 `--accept-review <anchor_id>`, 아니면 다시 생성 |
| 요약·관련성이 원문과 30자 이상 연속으로 같음 | 다시 생성 |
| 템플릿에 없는 줄 (기사 본문 문장·내부 메모 유입 의심) | 원인 확인 (스크립트 수정 필요) |
| private 원문 위치 형식 위반, 로컬 경로 문자열 | 원인 확인 |
| review 메모 문구가 파일에 들어감 | 원인 확인 |

## 중복과 덧붙이기

- public-ax `daily/`에 이미 있는 앵커 ID는 1~5단계 모두 기본으로 제외합니다 (`--include-published`로 포함).
- 날짜 파일이 이미 있으면 기존 블록은 그대로 두고 끝에 번호를 이어서 덧붙이며, `anchor_count`를 갱신합니다.
  같은 앵커 ID가 그 파일에 이미 있으면 덧붙이지 않습니다.
- `index.md`의 "일자별 앵커" 표와 `README.md`의 운영 현황 줄은 `daily/` 전체를 기준으로 다시 만듭니다.
