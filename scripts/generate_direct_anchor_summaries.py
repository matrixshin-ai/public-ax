"""
direct 앵커의 "짧은 사실 요약"과 "울산 AX 관련성"을 Claude API로 생성해
비공개 검토용 preview JSON(_work/direct_anchor_summaries_preview.json)에 저장한다.

- 대상: export_direct_anchors.py와 같은 direct 후보. 기본으로 public-ax daily/에 이미 있는
  anchor_id는 빼고 신규만 처리한다 (--include-published로 포함). --since / --date로 범위 지정.
- 각 기사 md의 frontmatter와 본문을 읽지만, 본문은 모델 입력에만 쓰고 콘솔에 출력하지 않는다.
  콘솔에는 건수·anchor_id·검사 결과만 나온다 (제목·URL·본문·생성 요약 출력 금지).
- 생성 결과는 anchor_safety.py 기준으로 자동 검사한다: 문장 수·길이, 원문과 연속으로 겹치는
  구간 길이(복사 방지), 관련성 라벨. 기준을 못 넘으면 사유를 알려주고 다시 생성한다
  (최대 --max-attempts회). 그래도 남은 문제는 preview의 review에 anchor_id별로 기록한다.
  export_direct_anchors.py는 review가 남은 anchor가 있으면 쓰기를 거부한다.
- preview는 누적 파일이다. 이미 있는 anchor_id는 건너뛰고(--regenerate로 다시 생성),
  이번 대상이 아닌 기존 항목도 지우지 않는다. 한 건 끝날 때마다 저장한다.
- public daily 파일은 만들지 않는다. _work/는 .gitignore 대상이다.

인증: ANTHROPIC_API_KEY 환경변수 (또는 Anthropic SDK가 읽는 다른 인증 방식).
모델: --model > 환경변수 AX_SUMMARY_MODEL > 기본 claude-sonnet-5.
"""
import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import anchor_safety as safety  # noqa: E402
import export_direct_anchors as exporter  # noqa: E402

PREVIEW_PATH = exporter.REPO_ROOT / "_work" / "direct_anchor_summaries_preview.json"
# 모델 우선순위: --model > 환경변수 AX_SUMMARY_MODEL > DEFAULT_MODEL (코드 수정 없이 바꿀 수 있게)
MODEL_ENV = "AX_SUMMARY_MODEL"
DEFAULT_MODEL = "claude-sonnet-5"
# 서버측 refusal fallback(fallbacks="default")을 받는 모델만 그 파라미터를 보낸다.
FALLBACK_MODELS = {"claude-fable-5-1", "claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5"}

RELEVANCE_LABELS = ("울산 직접 관련", "울산 정책 참고사례")
RELEVANCE_REASON_MAX_CHARS = 100

# 공용 검사 함수 (예전 이름 유지 - 다른 도구가 import해서 씀)
read_body = safety.read_body
longest_copy_run = safety.longest_copy_run
COPY_MAX_RUN = safety.COPY_MAX_RUN

SYSTEM_PROMPT = """당신은 공개 뉴스 색인 저장소 public-ax의 앵커 작성자입니다. 독자는 울산 산업 AX(AI 전환) 정책 담당자와 자문 전문가이고, 이 색인은 원문 기사를 찾아가기 위한 출발점입니다. 기사 전문을 대신하는 문서가 아닙니다.

기사 하나를 받으면 세 필드를 씁니다.

summary
- 한국어 1~2문장, 120자 안팎(최대 200자).
- 기사에서 확인되는 사실만 씁니다. 누가, 무엇을, 어디서 했는지가 드러나게 씁니다.
- 원문 문장을 그대로 옮기지 말고 자기 문장으로 다시 씁니다. 고유명사가 아닌 표현을 원문과 20자 넘게 똑같이 이어 쓰지 않습니다.
- 기업·기관·사업·기술 이름 같은 고유명사는 원문 표기 그대로 정확히 씁니다.
- 수치는 핵심적인 것 1~2개까지만 씁니다. 기사를 읽지 않아도 될 만큼 자세히 정리하지 않습니다.

relevance_type
- "울산 직접 관련": 울산 소재 기업·기관·현장, 또는 울산시 정책·사업이 기사 사실의 주체이거나 무대인 경우.
- "울산 정책 참고사례": 울산이 언급되지만 주체나 무대가 다른 지역·전국·해외이고, 울산 정책에 참고가 되는 경우.

relevance_reason
- 한국어 1문장, 최대 100자.
- 울산의 산업 AX, 제조 AX, 조선, 자동차, 에너지, 석유화학, AIDC, 인재양성, 공공 AX 중 어떤 관점과 연결되는지 씁니다.
- 기사에 없는 추측이나 평가는 쓰지 않습니다."""

OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "relevance_type": {"type": "string", "enum": list(RELEVANCE_LABELS)},
        "relevance_reason": {"type": "string"},
    },
    "required": ["summary", "relevance_type", "relevance_reason"],
    "additionalProperties": False,
}


def check(result: dict, body: str) -> list:
    """검사 실패 사유 목록 (빈 목록이면 통과)."""
    summary = (result.get("summary") or "").strip()
    reason = (result.get("relevance_reason") or "").strip()
    problems = safety.text_problems(summary, reason, body)
    if result.get("relevance_type") not in RELEVANCE_LABELS:
        problems.append("relevance_type이 허용값이 아님")
    if reason and safety.sentence_count(reason) > 1:
        problems.append(f"relevance_reason이 {safety.sentence_count(reason)}문장 (1문장이어야 함)")
    if len(reason) > RELEVANCE_REASON_MAX_CHARS:
        problems.append(f"relevance_reason이 {len(reason)}자 (최대 {RELEVANCE_REASON_MAX_CHARS}자)")
    return problems


def build_user_message(anchor: dict, body: str, problems: list) -> str:
    meta = (
        f"제목: {anchor['title']}\n"
        f"언론사: {anchor['source']}\n"
        f"날짜: {anchor['date']}\n"
        f"section: {anchor['section']}\n"
        f"industries: {', '.join(anchor['industries'])}"
    )
    msg = f"<article_meta>\n{meta}\n</article_meta>\n\n<article_body>\n{body}\n</article_body>"
    if problems:
        msg += "\n\n직전 결과가 다음 기준을 지키지 못했습니다. 고쳐서 다시 써 주세요.\n- " + "\n- ".join(problems)
    return msg


def call_model(client, model: str, effort: str, user_message: str):
    """(result dict | None, 실패 사유 | None)"""
    import anthropic

    params = dict(
        model=model,
        max_tokens=16000,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
        output_config={"effort": effort, "format": {"type": "json_schema", "schema": OUTPUT_SCHEMA}},
    )
    if model in FALLBACK_MODELS:
        # 안전 분류기가 거절하면 서버가 거절 범주에 맞는 모델로 같은 요청을 다시 실행한다.
        params.update(betas=["server-side-fallback-2026-07-01"], fallbacks="default")
    try:
        response = client.beta.messages.create(**params)
    except anthropic.BadRequestError as e:
        return None, f"요청 오류 400: {e.message}"
    except anthropic.AuthenticationError:
        raise
    except anthropic.APIStatusError as e:
        return None, f"API 오류 {e.status_code}"
    except anthropic.APIConnectionError:
        return None, "API 연결 실패"

    if response.stop_reason == "refusal":
        category = response.stop_details.category if response.stop_details else None
        return None, f"모델이 거절함 (category={category})"
    if response.stop_reason == "max_tokens":
        return None, "max_tokens에서 잘림"
    text = "".join(b.text for b in response.content if b.type == "text")
    try:
        return json.loads(text), None
    except json.JSONDecodeError:
        return None, "JSON 파싱 실패"


def load_preview() -> dict:
    if PREVIEW_PATH.exists():
        return json.loads(PREVIEW_PATH.read_text(encoding="utf-8"))
    return {}


def save_preview(items: dict, review: dict, model: str):
    """누적 저장: 이번 실행 대상이 아닌 기존 항목도 그대로 둔다."""
    ordered = sorted(items)
    data = {
        "source_system": "korea-industry-ax",
        "source_vault": "ax-vault-full",
        "scope": exporter.SCOPE,
        "anchor_count": len(items),
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "model": model,
        "items": [items[aid] for aid in ordered],
        # anchor_id -> 재시도 후에도 남은 검사 실패 사유 (사람 검토 필요)
        "review": {aid: review[aid] for aid in ordered if review.get(aid)},
    }
    PREVIEW_PATH.parent.mkdir(exist_ok=True)
    tmp = PREVIEW_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(PREVIEW_PATH)


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source",
                        help=f"ax-vault-full의 AX뉴스 폴더. 생략하면 환경변수 {exporter.selector.SOURCE_ENV}를 사용 "
                             f"(예: {exporter.selector.SOURCE_ENV}={exporter.selector.SOURCE_EXAMPLE})")
    exporter.selector.add_range_args(parser)
    parser.add_argument("--model", default=os.environ.get(MODEL_ENV) or DEFAULT_MODEL,
                        help=f"Claude 모델. 생략하면 환경변수 {MODEL_ENV}, 그것도 없으면 {DEFAULT_MODEL}")
    parser.add_argument("--effort", default="medium", choices=["low", "medium", "high", "xhigh", "max"],
                        help="output_config.effort (기본 medium)")
    parser.add_argument("--max-attempts", type=int, default=3, help="검사 실패 시 anchor당 최대 생성 횟수")
    parser.add_argument("--limit", type=int, help="앞에서부터 N건만 처리 (시험용)")
    parser.add_argument("--regenerate", action="store_true", help="preview에 이미 있는 anchor도 다시 생성")
    parser.add_argument("--check-only", action="store_true",
                        help="API를 호출하지 않고 대상 건수와 본문 읽기만 확인")
    args = parser.parse_args()

    source = exporter.resolve_source(args.source)
    exclude = frozenset() if args.include_published else frozenset(exporter.selector.published_anchor_ids())
    anchors = exporter.collect_anchors(source, args.since, args.on, exclude)
    if args.limit:
        anchors = anchors[:args.limit]
    paths = {p.name: p for p in source.rglob("*.md")}
    bodies = {a["anchor_id"]: safety.read_body(paths[Path(a["private_path"]).name]) for a in anchors}

    previous = load_preview()
    items = {it["anchor_id"]: it for it in previous.get("items", [])}
    review = dict(previous.get("review", {}))
    todo = [a for a in anchors if args.regenerate or a["anchor_id"] not in items]

    print("[preview 생성] 제목·URL·본문·생성 요약은 출력하지 않습니다.")
    rng = f"date={args.on}" if args.on else (f"since={args.since}" if args.since else "전체 기간")
    print(f"대상 anchor 수: {len(anchors)}  ({rng}, 이미 public-ax에 있는 {len(exclude)}건 제외 기준)")
    print(f"preview에 이미 있음: {len(anchors) - len(todo)}  /  새로 생성할 anchor: {len(todo)}")
    print(f"모델: {args.model}, effort: {args.effort}")
    empty_bodies = [aid for aid, b in bodies.items() if not b]
    print(f"본문이 비어 있는 anchor: {len(empty_bodies)}" + (f" {empty_bodies}" if empty_bodies else ""))
    if args.check_only:
        print("--check-only: API를 호출하지 않았습니다. preview 파일은 바뀌지 않았습니다.")
        return
    if not todo:
        print("새로 생성할 anchor가 없습니다.")
        return

    import anthropic

    try:
        client = anthropic.Anthropic(max_retries=4)
    except anthropic.AnthropicError as e:
        sys.exit(f"Anthropic 클라이언트를 만들 수 없습니다 (인증 정보 확인): {e}")
    print()

    counts = {"ok": 0, "review": 0, "failed": 0}
    for n, anchor in enumerate(todo, 1):
        aid = anchor["anchor_id"]
        body = bodies[aid]
        problems, result, attempts = [], None, 0
        while attempts < args.max_attempts:
            attempts += 1
            try:
                candidate, error = call_model(client, args.model, args.effort,
                                              build_user_message(anchor, body, problems))
            except anthropic.AuthenticationError:
                save_preview(items, review, args.model)
                sys.exit("인증 실패: ANTHROPIC_API_KEY를 확인하세요. 지금까지 결과는 저장했습니다.")
            if error:
                problems = [error]
                continue
            result = candidate
            problems = check(result, body)
            if not problems:
                break

        if result is None:
            counts["failed"] += 1
            review[aid] = problems
            print(f"  [{n:2d}/{len(todo)}] {aid}  실패 ({attempts}회): {'; '.join(problems)}")
            save_preview(items, review, args.model)
            continue
        items[aid] = {
            "anchor_id": aid,
            "summary": result["summary"].strip(),
            "ulsan_relevance": f"{result['relevance_type']}: {result['relevance_reason'].strip()}",
        }
        if problems:
            review[aid] = problems
            counts["review"] += 1
            status = f"검토 필요 ({attempts}회): {'; '.join(problems)}"
        else:
            review.pop(aid, None)
            counts["ok"] += 1
            status = f"통과 ({attempts}회)"
        print(f"  [{n:2d}/{len(todo)}] {aid}  {status}")
        save_preview(items, review, args.model)

    saved = load_preview()
    target = {a["anchor_id"] for a in anchors}
    mine = [it for it in saved["items"] if it["anchor_id"] in target]
    labels = {lbl: sum(1 for it in mine if it["ulsan_relevance"].startswith(lbl)) for lbl in RELEVANCE_LABELS}
    print("\n결과 (이번 대상 기준)")
    print(f"  통과 {counts['ok']} / 검토 필요 {counts['review']} / 실패 {counts['failed']}")
    print(f"  preview에 있는 대상 items: {len(mine)} / 대상 {len(target)}  (preview 전체 {len(saved['items'])}건)")
    print(f"  관련성 라벨: " + ", ".join(f"{k} {v}" for k, v in labels.items()))
    print(f"  검토 필요 anchor: {sorted(k for k in saved['review'] if k in target) or '없음'}")
    print(f"  저장: {PREVIEW_PATH.relative_to(exporter.REPO_ROOT).as_posix()}")


if __name__ == "__main__":
    main()
