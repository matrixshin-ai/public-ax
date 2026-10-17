# 신규 앵커 갱신 절차

`ax-vault-full`에 새로 들어온 기사 중 울산 직접 관련(scope: direct) 기사를 골라 public-ax daily 앵커로 추가하는 절차입니다.

## 자동 공개 (기본, 2026-10-17~)

GitHub Actions `auto-publish.yml`이 매일 KST 12:30에 사람 승인 없이 실행합니다. Actions 탭에서 `workflow_dispatch`로 바로 돌릴 수도 있습니다. 단 korea-industry-ax export가 도는 시간(대략 KST 08:50~12:00)에는 수동 실행을 피합니다.

1. ax-vault-full을 읽기 전용 deploy key로 받습니다.
2. 로그 규칙 테스트(`tests/`)를 돌립니다. 실패하면 공개하지 않습니다.
3. 이미 공개된 앵커 중 vault 원본 파일이 사라진 것을 찾아 내립니다(아래 "원본 소멸 자동 내림").
4. 마지막 공개 날짜 − 7일 이후의 미공개 direct 후보에 대해 요약을 생성하고(앵커당 최대 3회) 검사합니다.
5. 통과한 앵커와 내린 앵커를 daily·index·README·exclude에 반영하고 `master`에 커밋 1개로 push합니다. 공개·내림이 모두 0건이면 커밋하지 않습니다.
6. 새로 보류된 앵커가 있거나 실행이 실패하면 Issue를 엽니다. 매주 월요일 KST 15:00에 주간 요약 Issue가 열립니다.

| 판정 | 사유 코드 |
|---|---|
| 보류 (공개 안 함) | `SUMMARY_API_ERROR` `SUMMARY_REFUSAL` `SUMMARY_TRUNCATED` `SUMMARY_PARSE` `SUMMARY_EMPTY` `COPY_RUN`(원문과 50자 이상 연속 일치) `FIRST_SENTENCE_TOO_LONG` `TEMPLATE_LINE` `LOCAL_PATH` `REVIEW_NOTE_LEAK` `PENDING_LEFT` `PRIVATE_PATH_FORMAT` `FILE_CHECK_FAILED` |
| 품질 보정 후 공개 | `TOO_LONG`·`TOO_MANY_SENTENCES`(문장 단위로 자름), `RELEVANCE_LABEL`("울산 정책 참고사례"로 보정) |

- 사유 코드 뒤의 `:summary` / `:relevance`는 걸린 필드입니다.
- 보류 앵커는 7일 동안 매일 다시 시도합니다. 이미 열린 hold Issue에 있는 ID는 Issue를 다시 만들지 않습니다.
- 공개 로그에는 앵커 ID·사유 코드·건수·파일명만 나옵니다. 제목·URL·본문·요약은 나오지 않습니다.

### 원본 소멸 자동 내림

- korea-industry-ax는 어떤 기사가 다른 기사의 `related`로 병합되면 그 기사의 vault 파일을 지웁니다. 이미 공개된 앵커가 이렇게 되면, 다음 자동 실행이 그 블록을 내리고 `config/auto_publish_exclude.txt`에 `SOURCE_VANISHED`로 등록합니다. 대표 기사는 아직 공개되지 않았다면 같은 실행이나 다음 실행에서 따로 공개됩니다.
- 커밋 본문에는 `- unpublish <id> daily/<날짜>.md (SOURCE_VANISHED)`로 남고, 주간 요약에는 "원본 소멸로 내림: ID"로 표시됩니다.
- 한 번에 5건 넘게 사라졌으면 vault 체크아웃 이상일 수 있으므로 아무것도 내리지 않고 실행을 실패시킵니다. 실패 Issue에 `VANISHED_TOO_MANY`와 건수가 나옵니다. vault 상태를 확인한 뒤 정말 내려야 하면 아래 수동 스크립트로 한 건씩 내립니다.

## 공개한 앵커 내리기

```powershell
python scripts/unpublish_anchor.py <anchor_id>          # 계획만 출력 (dry-run)
python scripts/unpublish_anchor.py <anchor_id> --write  # 실제 반영
git diff                                                # 확인 후 commit / push
```

- 그 앵커 블록을 지우고 같은 파일의 번호·`anchor_count`, `index.md` 표, `README.md` 운영 현황을 다시 계산합니다. 남은 앵커가 없으면 날짜 파일을 지웁니다.
- `config/auto_publish_exclude.txt`에 ID를 등록해 자동·수동 갱신이 다시 고르지 않게 합니다. `git revert`만 하면 다음 날 자동 실행이 다시 공개하므로 이 스크립트를 씁니다.
- 보류 중인 앵커를 영구히 공개하지 않으려면 exclude 파일에 ID만 추가하고 hold Issue를 닫습니다.

## 수동 갱신 (예비용)

자동 공개가 멈췄거나 특정 앵커를 사람이 확인하고 넣을 때 씁니다. 각 단계의 결과를 사람이 확인한 뒤 다음 단계로 넘어갑니다.

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
| 요약·관련성이 원문과 50자 이상 연속으로 같음 | 다시 생성 |
| 템플릿에 없는 줄 (기사 본문 문장·내부 메모 유입 의심) | 원인 확인 (스크립트 수정 필요) |
| private 원문 위치 형식 위반, 로컬 경로 문자열 | 원인 확인 |
| review 메모 문구가 파일에 들어감 | 원인 확인 |

## 중복과 덧붙이기

- public-ax `daily/`에 이미 있는 앵커 ID와 `config/auto_publish_exclude.txt`의 ID는 1~5단계 모두 기본으로 제외합니다 (`--include-published`로 포함).
- 날짜 파일이 이미 있으면 기존 블록은 그대로 두고 끝에 번호를 이어서 덧붙이며, `anchor_count`를 갱신합니다.
  같은 앵커 ID가 그 파일에 이미 있으면 덧붙이지 않습니다.
- `index.md`의 "일자별 앵커" 표와 `README.md`의 운영 현황 줄은 `daily/` 전체를 기준으로 다시 만듭니다.
