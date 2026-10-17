"""
public-ax 자동 공개 (GitHub Actions auto-publish.yml 전용, 사람 승인 단계 없음).

- 후보: 마지막 공개 날짜 - LOOKBACK_DAYS일 이후의 direct 앵커 중 아직 공개되지 않았고
  config/auto_publish_exclude.txt에 없는 것. 보류된 앵커는 이 기간 동안 매일 다시 시도한다.
- 요약: generate_direct_anchor_summaries.py와 같은 프롬프트·모델 호출(앵커당 최대 3회).
- 공개 조건: 요약 존재 + COPY_RUN 없음 + 유출 검사 통과.
  - 보류(공개 안 함): 요약 생성 실패(SUMMARY_*), COPY_RUN(50자), 첫 문장만으로 길이 초과,
    TEMPLATE_LINE, LOCAL_PATH, REVIEW_NOTE_LEAK, PENDING_LEFT, PRIVATE_PATH_FORMAT,
    FILE_CHECK_FAILED(파일 단위 검사 실패 - 그 파일에 붙을 앵커만).
  - 품질 보정 후 공개: TOO_LONG·TOO_MANY_SENTENCES(문장 단위로 자름), RELEVANCE_LABEL
    ("울산 정책 참고사례"로 보정). 보정 코드는 커밋 메시지와 주간 요약에 ID와 함께 남는다.
  - 요약·관련성의 줄바꿈·연속 공백은 검사 전에 한 칸으로 정리한다.
- 원본 소멸: 공개된 앵커의 vault 파일(파일명 끝 anchor_id 기준)이 사라졌으면(예: 다른 기사의
  related로 병합) 그 블록을 내리고 exclude에 등록한다(SOURCE_VANISHED). 한 번에 MAX_VANISHED건을
  넘게 사라졌으면 vault 체크아웃 이상으로 보고 아무것도 하지 않고 실패한다(VANISHED_TOO_MANY).
- 출력 규칙(공개 로그): 건수·anchor_id·사유 코드·daily 파일명만 출력한다. 기사 제목·URL·본문,
  원문 일치 문장, 생성 요약·관련성 문장, API 오류 원문은 출력하지 않는다. 예외도 타입 이름만.
  tests/test_auto_publish_logs.py가 이 규칙을 검증한다.
- --report: 결과 JSON(ID·코드·파일명만), --commit-message: 커밋 메시지 파일(신규 0건이면 만들지 않음).
"""
import argparse
import collections
import json
import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import anchor_safety as safety  # noqa: E402
import export_direct_anchors as exporter  # noqa: E402
import generate_direct_anchor_summaries as gen  # noqa: E402
import unpublish_anchor  # noqa: E402

selector = exporter.selector
KST = timezone(timedelta(hours=9))
LOOKBACK_DAYS = 7
MAX_ATTEMPTS = 3
MAX_VANISHED = 5  # 한 번에 이보다 많이 사라지면 오작동으로 보고 내리지 않는다
VANISHED_CODE = "SOURCE_VANISHED"
FALLBACK_LABEL = "울산 정책 참고사례"  # 라벨이 허용값 밖일 때 보수적인 쪽으로 보정
COMMIT_PREFIX = "auto-publish"

# 재시도 후에도 남으면 보류하는 문장 검사 코드 (나머지 문장 검사 코드는 품질 보정 대상)
HOLD_TEXT_CODES = {"COPY_RUN", "SUMMARY_EMPTY"}
LIMITS = {  # 필드 -> (결과 키, 최대 문장 수, 최대 글자 수)
    "summary": ("summary", 2, safety.SUMMARY_MAX_CHARS),
    "relevance": ("relevance_reason", 1, gen.RELEVANCE_REASON_MAX_CHARS),
}


class VanishedTooMany(Exception):
    def __init__(self, count: int):
        super().__init__(count)
        self.count = count


def log(msg: str = ""):
    print(msg, flush=True)


def find_vanished(source: Path, texts: dict) -> list:
    """공개된 anchor_id 중 vault에 파일이 없는 것."""
    present = {m.group(1) for p in source.rglob("*.md") if (m := selector.ANCHOR_ID_RE.search(p.name))}
    published = set().union(*(selector.PUBLISHED_ID_RE.findall(t) for t in texts.values()))
    return sorted(published - present)


def codes_of(issues) -> list:
    """[(코드, 필드, 메시지)] -> ["코드:필드", ...] (메시지는 버린다)."""
    return sorted({f"{c}:{f}" for c, f, _ in issues})


def generate(client, model: str, effort: str, anchor: dict, body: str, max_attempts: int):
    """(result | None, 마지막 검사 issues, 실패 코드 | None).
    검사를 통과하면 바로 돌려준다. 끝까지 남으면 보류 코드가 없는 결과를 우선으로 돌려준다."""
    feedback, last, fallback, error = [], None, None, None
    for _ in range(max_attempts):
        result, err = gen.call_model_coded(client, model, effort, gen.build_user_message(anchor, body, feedback))
        if err:
            error, feedback = err[0], [err[1]]
            continue
        result = {k: safety.squash(str(result.get(k) or "")) for k in ("summary", "relevance_type", "relevance_reason")}
        issues = gen.check_issues(result, body)
        if not issues:
            return result, [], None
        last = (result, issues)
        if not any(c in HOLD_TEXT_CODES for c, _, _ in issues):
            fallback = (result, issues)
        feedback = [m for _, _, m in issues]
    if fallback or last:
        result, issues = fallback or last
        return result, issues, None
    return None, [], error


def finalize(result: dict, issues: list, body: str):
    """(공개할 result | None, 보류 코드, 품질 보정 코드)."""
    hold = [c for c in codes_of(issues) if c.split(":")[0] in HOLD_TEXT_CODES]
    if hold:
        return None, hold, []
    fixed, quality = dict(result), []
    present = {(c, f) for c, f, _ in issues}
    if ("RELEVANCE_LABEL", "relevance") in present:
        fixed["relevance_type"] = FALLBACK_LABEL
        quality.append("RELEVANCE_LABEL:relevance")
    for field, (key, max_sentences, max_chars) in LIMITS.items():
        found = sorted(c for c, f in present if f == field and c in ("TOO_LONG", "TOO_MANY_SENTENCES"))
        if not found:
            continue
        cut = safety.truncate_sentences(fixed[key], max_sentences, max_chars)
        if cut is None:
            return None, [f"FIRST_SENTENCE_TOO_LONG:{field}"], []
        fixed[key] = cut
        quality += [f"{c}:{field}" for c in found]
    remaining = gen.check_issues(fixed, body)  # 보정 뒤 다시 검사 (남으면 보류)
    if remaining:
        return None, codes_of(remaining), []
    return fixed, [], sorted(quality)


def block_issue_codes(anchor: dict, notes: list) -> list:
    """앵커 블록 하나만 렌더링해 유출·형식 검사. ["코드", ...]"""
    text = "\n".join(exporter.render_block(1, anchor))
    return sorted({code for _, code, _ in safety.daily_text_issues(text, notes)})


def last_published_date(daily_dir: Path):
    dates = sorted(f.stem for f in daily_dir.glob("????-??-??.md"))
    return dates[-1] if dates else None


def run(source: Path, repo_root: Path, client, model: str, effort: str = "medium",
        max_attempts: int = MAX_ATTEMPTS, lookback_days: int = LOOKBACK_DAYS, write: bool = False,
        today: str = None) -> dict:
    daily_dir = repo_root / "daily"
    exclude_path = repo_root / "config" / "auto_publish_exclude.txt"
    today = today or datetime.now(KST).date().isoformat()
    texts = {f.stem: f.read_text(encoding="utf-8") for f in sorted(daily_dir.glob("????-??-??.md"))}

    # 원본 소멸 앵커 내리기 (메모리에서만, 쓰기는 마지막에 한 번에)
    vanished = find_vanished(source, texts)
    if len(vanished) > MAX_VANISHED:
        raise VanishedTooMany(len(vanished))
    unpublished, touched = [], set()  # touched: 블록을 지운 날짜
    for aid in vanished:
        for d in sorted(texts):
            if texts[d] and aid in selector.PUBLISHED_ID_RE.findall(texts[d]):
                texts[d], _ = unpublish_anchor.remove_block(texts[d], aid)  # None = 블록이 하나도 안 남음
                touched.add(d)
                unpublished.append({"id": aid, "daily": f"daily/{d}.md", "reason": VANISHED_CODE})

    last = last_published_date(daily_dir)
    since = (date.fromisoformat(last) - timedelta(days=lookback_days)).isoformat() if last else None
    exclude = selector.published_anchor_ids(daily_dir) | selector.excluded_anchor_ids(exclude_path)
    anchors = exporter.collect_anchors(source, since, None, frozenset(exclude))
    log(f"[auto-publish] {today} since={since} 대상 {len(anchors)}건, 원본 소멸 {len(vanished)}건, 모델 {model} "
        "(제목·URL·본문·요약은 출력하지 않습니다)")

    held, quality, ready, notes = {}, {}, [], []
    for a in anchors:
        aid = a["anchor_id"]
        body = safety.read_body(a["_vault_file"])
        result, issues, error = generate(client, model, effort, a, body, max_attempts)
        notes += [m for _, _, m in issues]
        if result is None:
            held[aid] = [error or "SUMMARY_EMPTY"]
            continue
        fixed, hold, q = finalize(result, issues, body)
        if fixed is None:
            held[aid] = hold
            continue
        a["summary"] = fixed["summary"]
        a["ulsan_relevance"] = f"{fixed['relevance_type']}: {fixed['relevance_reason']}"
        quality[aid] = q
        ready.append(a)

    # 앵커 블록 단위 유출·형식 검사 -> 걸린 앵커만 보류
    passing = []
    for a in ready:
        codes = block_issue_codes(a, notes)
        if codes:
            held[a["anchor_id"]] = codes
        else:
            passing.append(a)

    # 날짜 파일 단위 검사 -> 실패하면 그 파일에 붙을 앵커만 보류
    by_date = collections.defaultdict(list)
    for a in passing:
        by_date[a["date"]].append(a)
    planned = {}
    for d, items in sorted(by_date.items()):
        existing = texts.get(d) or ""
        text, added, _ = exporter.append_daily(existing, items) if existing else (
            exporter.render_daily(d, items), len(items), 0)
        file_codes = sorted({code for _, code, _ in safety.daily_text_issues(text, notes)})
        if file_codes:
            for a in items:
                held[a["anchor_id"]] = ["FILE_CHECK_FAILED"] + file_codes
            continue
        if added:
            planned[d] = (text, items)

    published = [{"id": a["anchor_id"], "daily": f"daily/{d}.md", "quality": quality.get(a["anchor_id"], [])}
                 for d, (_, items) in sorted(planned.items()) for a in items]
    for d, (text, _) in planned.items():
        texts[d] = text
    for d in touched - set(planned):  # 블록만 지운 파일도 쓰기 전에 검사
        if texts[d] is not None and safety.daily_text_issues(texts[d]):
            raise RuntimeError("UNPUBLISH_CHECK_FAILED")
    if write and (planned or touched):
        for d in set(planned) | touched:
            path = daily_dir / f"{d}.md"
            if texts[d] is None:
                path.unlink(missing_ok=True)
            else:
                path.write_text(texts[d], encoding="utf-8", newline="\n")
        counts = exporter.daily_counts({d: t for d, t in texts.items() if t is not None})
        new_index, new_readme = exporter.updated_index_and_readme(
            counts, repo_root / "index.md", repo_root / "README.md")
        (repo_root / "index.md").write_text(new_index, encoding="utf-8", newline="\n")
        (repo_root / "README.md").write_text(new_readme, encoding="utf-8", newline="\n")
        for u in unpublished:
            unpublish_anchor.add_exclude(exclude_path, u["id"], today, VANISHED_CODE)

    for u in unpublished:
        log(f"  UNPUBLISH {u['id']} {u['daily']} {u['reason']}")
    for p in published:
        log(f"  PUBLISH {p['id']} {p['daily']}" + (f" QUALITY {','.join(p['quality'])}" if p["quality"] else ""))
    for aid in sorted(held):
        log(f"  HOLD    {aid} {','.join(held[aid])}")
    n_quality = sum(1 for p in published if p["quality"])
    log(f"결과: 공개 {len(published)} / 보류 {len(held)} / 품질 보정 공개 {n_quality}"
        f" / 원본 소멸로 내림 {len(unpublished)}" + ("" if write else " (dry-run: 파일을 쓰지 않음)"))
    return {
        "date": today,
        "since": since,
        "candidates": len(anchors),
        "published": published,
        "held": [{"id": aid, "codes": held[aid]} for aid in sorted(held)],
        "unpublished": unpublished,
    }


def commit_message(report: dict):
    """공개·내림이 모두 0건이면 None. 본문 한 줄에 앵커 하나 (ID·daily 파일·코드만)."""
    pub, unpub = report["published"], report.get("unpublished", [])
    if not pub and not unpub:
        return None
    title = f"{COMMIT_PREFIX} {report['date']}: {len(pub)} anchors"
    if unpub:
        title += f", {len(unpub)} unpublished"
    lines = [title, ""]
    for p in pub:
        lines.append(f"- {p['id']} {p['daily']}" + (f" [quality: {','.join(p['quality'])}]" if p["quality"] else ""))
    for u in unpub:
        lines.append(f"- unpublish {u['id']} {u['daily']} ({u['reason']})")
    return "\n".join(lines) + "\n"


def main(argv=None, client=None):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source", help=f"ax-vault-full의 AX뉴스 폴더 (생략하면 환경변수 {selector.SOURCE_ENV})")
    parser.add_argument("--repo-root", default=str(exporter.REPO_ROOT), help=argparse.SUPPRESS)
    parser.add_argument("--model", default=os.environ.get(gen.MODEL_ENV) or gen.DEFAULT_MODEL)
    parser.add_argument("--effort", default="medium", choices=["low", "medium", "high", "xhigh", "max"])
    parser.add_argument("--max-attempts", type=int, default=MAX_ATTEMPTS)
    parser.add_argument("--lookback-days", type=int, default=LOOKBACK_DAYS)
    parser.add_argument("--today", type=selector.iso_date, help="기준 날짜 (기본: 오늘 KST)")
    parser.add_argument("--write", action="store_true", help="daily·index·README를 실제로 씀 (없으면 dry-run)")
    parser.add_argument("--report", help="결과 JSON 경로 (ID·코드·파일명만)")
    parser.add_argument("--commit-message", help="커밋 메시지 파일 경로 (신규 0건이면 만들지 않음)")
    args = parser.parse_args(argv)
    try:
        source_arg = args.source or os.environ.get(selector.SOURCE_ENV)
        if not source_arg or not Path(source_arg).is_dir():
            log("ERROR SOURCE_MISSING")  # 경로는 출력하지 않는다
            return 2
        if client is None:
            import anthropic
            client = anthropic.Anthropic(max_retries=4)
        report = run(Path(source_arg), Path(args.repo_root), client, args.model, args.effort,
                     args.max_attempts, args.lookback_days, args.write, args.today)
        if args.report:
            Path(args.report).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        msg = commit_message(report)
        if args.commit_message and msg:
            Path(args.commit_message).write_text(msg, encoding="utf-8", newline="\n")
        return 0
    except VanishedTooMany as e:
        log(f"ERROR VANISHED_TOO_MANY count={e.count} (최대 {MAX_VANISHED}건) - 아무것도 내리지 않았습니다")
        write_error(args.report, "VANISHED_TOO_MANY", vanished_count=e.count)
        return 1
    except Exception as e:  # noqa: BLE001 - traceback·예외 메시지는 기사 내용을 담을 수 있어 타입만 출력
        code = str(e) if str(e) == "UNPUBLISH_CHECK_FAILED" else type(e).__name__
        log(f"ERROR {code}")
        write_error(args.report, code)
        return 1


def write_error(report_path, code: str, **extra):
    """실패 Issue가 사유 코드를 읽을 수 있게 결과 JSON에 남긴다 (코드·건수만)."""
    if report_path:
        Path(report_path).write_text(json.dumps({"error": code, **extra}), encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())
