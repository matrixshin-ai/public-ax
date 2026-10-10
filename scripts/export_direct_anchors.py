"""
ax-vault-full -> public-ax daily 앵커 exporter (scope: direct 고정).

- 후보 선별은 dry_run_select_anchors.py의 frontmatter 읽기·분류 로직을 그대로 쓴다.
  scope는 direct(A그룹, 울산 직접 관련)로 고정이다.
- 신규 갱신용: public-ax daily/에 이미 있는 anchor_id는 기본으로 뺀다(--include-published로
  포함). --since YYYY-MM-DD / --date YYYY-MM-DD로 범위를 좁힌다.
- 기본 실행은 dry-run이다. 파일을 쓰지 않고 건수·예정 경로·검사 결과·anchor_id만 출력한다.
  --write를 줬을 때만 파일을 쓴다.
  - 날짜 파일이 없으면 새로 만들고, 있으면 기존 블록은 그대로 두고 끝에 덧붙인다(append).
    같은 anchor_id가 이미 그 파일에 있으면 덧붙이지 않는다. anchor_count도 갱신한다.
  - 쓰고 나면 index.md의 "## 일자별 앵커" 표와 README.md의 운영 현황 줄을 daily/ 전체
    기준(파일 수·앵커 수·기간)으로 다시 만든다.
- daily 파일에는 제목·언론사·날짜·URL·분류값·public-ax tags·private 원문 위치와
  --summaries JSON(generate_direct_anchor_summaries.py가 만든 _work/ preview)의
  짧은 사실 요약·울산 AX 관련성만 쓴다. preview의 review(검토 메모)는 쓰지 않는다.
- 쓰기 전 중단 조건 (dry-run에서도 같은 검사를 하고 결과를 보여 준다):
  - summaries에 없는 anchor_id (--allow-missing-summaries일 때만 [미작성]으로 둠)
  - summary·ulsan_relevance가 빈 값
  - 이번 대상 중 preview review가 남은 anchor (--accept-review ID,...로 명시 허용한 것만 통과)
  - 공개 안전성 검사(anchor_safety.py) 실패: 요약·관련성의 원문 복사, 템플릿 밖의 줄(본문
    문장·내부 메모 유입), private 원문 위치 형식 위반·로컬 경로, review 메모 문구
- 콘솔에는 제목·URL·본문·요약을 출력하지 않는다. 단 --print-preview를 주면 사람 검토용으로
  이번 대상의 제목·출처·요약·관련성을 출력한다 (URL·본문은 출력하지 않음).
"""
import argparse
import collections
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import anchor_safety as safety  # noqa: E402
import dry_run_select_anchors as selector  # noqa: E402

SCOPE = "direct"
REPO_ROOT = selector.REPO_ROOT
DAILY_DIR = selector.DAILY_DIR
INDEX_PATH = REPO_ROOT / "index.md"
README_PATH = REPO_ROOT / "README.md"
DEFAULT_SUMMARIES = "_work/direct_anchor_summaries_preview.json"
VAULT_PREFIX = "ax-vault-full/AX뉴스"
PENDING = safety.PENDING

# public-ax tags - 원본 tags를 복사하지 않고 title·industries·section에서 새로 만든다.
TAG_KEYWORDS = [
    "조선", "자동차", "석유화학", "화학", "에너지", "수소", "배터리", "데이터센터", "AIDC",
    "제조AX", "산업AX", "제조AI", "피지컬AI", "디지털트윈", "자율제조", "스마트팩토리", "로봇",
    "인재양성", "정책", "기업현장", "기술인프라",
]
SECTION_TAGS = {
    "정책·생태계·인재": "정책",
    "기업·현장": "기업현장",
    "기술·인프라": "기술인프라",
}
# 더 긴 태그가 이미 있으면 그 부분 문자열 태그는 붙이지 않는다 (석유화학 -> 화학 중복 방지).
TAG_SUBSUMED_BY = {"화학": "석유화학"}

GRADE_ORDER = {"S": 0, "A": 1}
ANCHOR_COUNT_RE = re.compile(r"^anchor_count: (\d+)$", re.M)
BLOCK_HEAD_RE = re.compile(r"^### (\d+)\. ", re.M)
INDEX_SECTION_RE = re.compile(r"^## 일자별 앵커\n.*?(?=^## )", re.M | re.S)
README_STATUS_RE = re.compile(r"^- 운영 현황: .*$", re.M)


def resolve_source(arg):
    source_arg = arg or os.environ.get(selector.SOURCE_ENV)
    if not source_arg:
        sys.exit(
            "원자료 폴더가 지정되지 않았습니다.\n"
            f"  --source로 지정하거나 환경변수 {selector.SOURCE_ENV}를 설정하세요.\n"
            f"  예) python scripts/export_direct_anchors.py --source \"{selector.SOURCE_EXAMPLE}\"\n"
            f"  예) PowerShell: $env:{selector.SOURCE_ENV} = \"{selector.SOURCE_EXAMPLE}\"\n"
            f"  예) bash:       export {selector.SOURCE_ENV}=\"{selector.SOURCE_EXAMPLE}\""
        )
    source = Path(source_arg)
    if not source.is_dir():
        sys.exit(f"source 폴더가 없습니다: {source}")
    return source


def load_summaries(arg: str, anchors: list, allow_missing: bool):
    """({anchor_id: {summary, ulsan_relevance}}, {anchor_id: review 사유}, 집계).
    누락·빈 값이면 sys.exit. review는 중단 판정에만 쓰고 daily 파일에는 쓰지 않는다."""
    path = Path(arg)
    if not path.is_absolute() and not path.exists():
        path = REPO_ROOT / arg  # 저장소 루트 기준 상대경로도 허용
    if not path.exists():
        if allow_missing:
            return {}, {}, {"loaded": 0, "missing": len(anchors), "path": arg}
        sys.exit(f"summaries 파일이 없습니다: {arg}\n"
                 "  scripts/generate_direct_anchor_summaries.py로 먼저 만들거나 --allow-missing-summaries를 쓰세요.")
    data = json.loads(path.read_text(encoding="utf-8"))
    by_id = {it.get("anchor_id"): it for it in data.get("items", [])}
    target = {a["anchor_id"] for a in anchors}

    empty = [aid for aid, it in by_id.items() if aid in target and (
        not str(it.get("summary") or "").strip() or not str(it.get("ulsan_relevance") or "").strip())]
    if empty:
        sys.exit(f"summary 또는 ulsan_relevance가 빈 항목이 있습니다: {sorted(empty)}")
    missing = [aid for aid in sorted(target) if aid not in by_id]
    if missing and not allow_missing:
        sys.exit(f"summaries에 없는 anchor_id {len(missing)}건: {missing}\n"
                 "  generate_direct_anchor_summaries.py를 같은 --since/--date로 실행하거나, "
                 "[미작성]으로 두려면 --allow-missing-summaries를 쓰세요.")
    summaries = {aid: {"summary": str(it["summary"]).strip(), "ulsan_relevance": str(it["ulsan_relevance"]).strip()}
                 for aid, it in by_id.items() if aid in target}
    review = {aid: v for aid, v in data.get("review", {}).items() if v}
    loaded = sum(1 for aid in target if aid in by_id)
    return summaries, review, {"loaded": loaded, "missing": len(missing), "path": arg}


def build_tags(fm: dict) -> list:
    haystack = [selector.norm(fm.get("title") or ""), selector.norm(fm.get("section") or "")]
    haystack += [selector.norm(i) for i in selector.as_list(fm.get("industries"))]
    tags = ["울산"]
    for kw in TAG_KEYWORDS:
        if any(selector.norm(kw) in h for h in haystack):
            tags.append(kw)
    section_tag = SECTION_TAGS.get(fm.get("section"))
    if section_tag:
        tags.append(section_tag)
    tags = [t for t in tags if TAG_SUBSUMED_BY.get(t) not in tags]
    return list(dict.fromkeys(tags))  # 순서 유지 중복 제거


def collect_anchors(source: Path, since: str = None, on: str = None, exclude_ids=frozenset()) -> list:
    selected_groups = selector.SCOPES[SCOPE]
    anchors = []
    for path in sorted(source.rglob("*.md")):
        fm = selector.read_frontmatter(path)
        if not fm:
            continue
        date = selector.normalize_date(fm.get("date"), path)
        if not selector.in_date_range(date, since, on):
            continue
        group, _ = selector.classify(fm)
        if group not in selected_groups:
            continue
        m = selector.ANCHOR_ID_RE.search(path.name)
        anchor_id = m.group(1) if m else "no-id"
        if anchor_id in exclude_ids:
            continue
        anchors.append({
            "anchor_id": anchor_id,
            "date": date,
            "title": str(fm.get("title") or "").strip(),
            "source": str(fm.get("source") or "").strip(),
            "url": str(fm.get("url") or "").strip(),
            "grade": str(fm.get("grade") or "").strip(),
            "section": str(fm.get("section") or "").strip(),
            "industries": selector.as_list(fm.get("industries")),
            "tags": build_tags(fm),
            "private_path": f"{VAULT_PREFIX}/{path.relative_to(source).as_posix()}",
            "_vault_file": path,  # 안전성 검사용 (daily 파일에는 쓰지 않음)
        })
    anchors.sort(key=lambda a: (a["date"], GRADE_ORDER.get(a["grade"], 9), a["anchor_id"]))
    return anchors


def render_block(i: int, a: dict) -> list:
    return [
        "",
        f"### {i}. {a['title'] or '(제목 없음)'}",
        "",
        f"- 앵커 ID: {a['anchor_id']}",
        f"- 날짜: {a['date']}",
        f"- 출처: {a['source']}",
        f"- 원문 URL: {a['url']}",
        f"- 수집 등급: {a['grade']}",
        f"- section: {a['section']}",
        f"- industries: {', '.join(a['industries'])}",
        "- tags:",
        *[f"  - {t}" for t in a["tags"]],
        f"- 짧은 사실 요약: {a.get('summary') or PENDING}",
        f"- 울산 AX 관련성: {a.get('ulsan_relevance') or PENDING}",
        f"- private 원문 위치: {a['private_path']}",
    ]


def render_daily(date: str, anchors: list) -> str:
    lines = [
        "---",
        f"date: {date}",
        "source_system: korea-industry-ax",
        "source_vault: ax-vault-full",
        f"scope: {SCOPE}",
        f"anchor_count: {len(anchors)}",
        "---",
        "",
        f"# {date} AX direct anchors",
        "",
        "> korea-industry-ax 수록 기사 중 울산 직접 관련성이 높은 공개 앵커입니다. 기사 전문은 포함하지 않습니다.",
        "",
        "## 앵커 목록",
    ]
    for i, a in enumerate(anchors, 1):
        lines += render_block(i, a)
    return "\n".join(lines) + "\n"


def append_daily(existing: str, anchors: list):
    """(새 텍스트, 덧붙인 수, 중복이라 건너뛴 수). 기존 블록은 한 글자도 바꾸지 않는다."""
    present = set(selector.PUBLISHED_ID_RE.findall(existing))
    new = [a for a in anchors if a["anchor_id"] not in present]
    n = len(BLOCK_HEAD_RE.findall(existing))
    if not new:
        return existing, 0, len(anchors)
    lines = []
    for i, a in enumerate(new, n + 1):
        lines += render_block(i, a)
    text = existing.rstrip("\n") + "\n" + "\n".join(lines) + "\n"
    text = ANCHOR_COUNT_RE.sub(f"anchor_count: {n + len(new)}", text, count=1)
    return text, len(new), len(anchors) - len(new)


def daily_counts(texts: dict) -> dict:
    """{date: anchor_count} - texts는 {date: daily 파일 내용}."""
    return {d: int(ANCHOR_COUNT_RE.search(t).group(1)) for d, t in texts.items()}


def render_index_section(counts: dict) -> str:
    dates = sorted(counts)
    lines = ["## 일자별 앵커", "",
             "울산 직접 관련(scope: direct) 공개 앵커를 날짜별로 모은 파일입니다. 기사 전문은 포함하지 않습니다.", "",
             "| 날짜 | 앵커 수 | 파일 |", "|---|---:|---|"]
    lines += [f"| {d} | {counts[d]} | [daily/{d}.md](daily/{d}.md) |" for d in dates]
    lines += ["", f"- 파일 수: {len(dates)}개", f"- 앵커 수: {sum(counts.values())}건",
              f"- 범위: {dates[0]} ~ {dates[-1]}" if dates else "- 범위: -", f"- scope: {SCOPE}", "", ""]
    return "\n".join(lines)


def render_readme_status(counts: dict) -> str:
    dates = sorted(counts)
    return (f"- 운영 현황: direct daily anchors {len(dates)} files, {sum(counts.values())} anchors "
            f"({dates[0]} ~ {dates[-1]}) — [일자별 앵커 목록](index.md#일자별-앵커)")


def updated_index_and_readme(counts: dict):
    index = INDEX_PATH.read_text(encoding="utf-8")
    section = render_index_section(counts)
    if INDEX_SECTION_RE.search(index):
        new_index = INDEX_SECTION_RE.sub(lambda _: section, index, count=1)
    else:
        new_index = index.replace("## 운영 원칙", section + "## 운영 원칙", 1)
    readme = README_PATH.read_text(encoding="utf-8")
    new_readme = README_STATUS_RE.sub(lambda _: render_readme_status(counts), readme, count=1)
    return new_index, new_readme


def safety_check(planned: dict, anchors: list, review: dict, allow_pending: bool, accepted=frozenset()) -> list:
    """쓰기 전 공개 안전성 검사. 문제 목록(파일·anchor_id·종류만, 내용 없음).
    문장 검사(복사·길이)는 이번에 실제로 덧붙일 anchor만, --accept-review로 사람이 허용한 것은 뺀다."""
    problems = []
    notes = [p for ps in review.values() for p in ps]
    for date, (text, _, _) in planned.items():
        for p in safety.daily_text_problems(text, notes, allow_pending):
            problems.append(f"daily/{date}.md {p}")
    for a in anchors:
        if not a.get("summary") or a["anchor_id"] in accepted or not a.get("_will_add"):
            continue
        body = safety.read_body(a["_vault_file"])
        for p in safety.text_problems(a["summary"], a["ulsan_relevance"], body):
            problems.append(f"{a['anchor_id']}: {p}")
    return problems


def print_report(anchors, by_date, planned, write, limit_ids, summary_stats, blocking, counts_after, excluded,
                 existed):
    def table(title, counter):
        print(title)
        for k, v in counter.most_common():
            print(f"  {v:5d}  {k}")

    mode = "WRITE" if write else "dry-run (파일을 쓰지 않습니다)"
    print(f"[{mode}] scope={SCOPE}. 제목·URL·본문·요약은 출력하지 않습니다.\n")
    print(f"1. 신규 anchor 수: {len(anchors)}  (이미 public-ax에 있어 제외한 anchor_id 기준 {excluded}건)")
    filled = sum(1 for a in anchors if a.get("summary"))
    print(f"   summaries: {summary_stats['path']} - 대상 중 {summary_stats['loaded']}건 있음, "
          f"누락 {summary_stats['missing']}건, 요약이 채워질 anchor {filled}/{len(anchors)}")
    print(f"2. 대상 daily 파일 수: {len(by_date)}")
    print("3. 날짜별 신규 anchor 수")
    for date in sorted(by_date):
        print(f"  {len(by_date[date]):5d}  {date}")
    table("4. section별", collections.Counter(a["section"] or "(없음)" for a in anchors))
    table("5. grade별", collections.Counter(a["grade"] or "(없음)" for a in anchors))
    table("6. industries별", collections.Counter(i for a in anchors for i in (a["industries"] or ["(없음)"])))
    print("7. 파일별 계획")
    for date, (_, added, dup) in sorted(planned.items()):
        verb = "덧붙임" if existed[date] else "새로 만듦"  # 쓰기 전 상태 기준
        done = "완료" if write and not blocking else "예정"
        print(f"  daily/{date}.md  {verb} {added}건 {done}" + (f", 중복이라 건너뜀 {dup}건" if dup else ""))
    if counts_after:
        dates = sorted(counts_after)
        print(f"8. 반영 후 index.md 기준: 파일 {len(dates)}개, 앵커 {sum(counts_after.values())}건, "
              f"범위 {dates[0]} ~ {dates[-1]}")
    print("9. 쓰기 전 검사")
    if blocking:
        print(f"  중단 사유 {len(blocking)}건:")
        for b in blocking:
            print(f"   - {b}")
    else:
        print("  통과 (누락·빈 값·review·공개 안전성 문제 없음)")
    ids = [a["anchor_id"] for a in sorted(anchors, key=lambda a: (a["date"], a["anchor_id"]), reverse=True)]
    print(f"10. 신규 anchor_id {min(limit_ids, len(ids))}개 (최신 날짜순)")
    for aid in ids[:limit_ids]:
        print(f"  {aid}")


def print_preview(anchors: list, review: dict):
    """--print-preview: 사람 검토용. 공개 예정인 값만 출력하고 URL·본문은 출력하지 않는다."""
    print("\n[요약 preview - 사람 검토용, URL·본문 제외]")
    for a in anchors:
        flag = "  ⚠ review: " + "; ".join(review[a["anchor_id"]]) if a["anchor_id"] in review else ""
        print(f"\n- {a['date']} {a['anchor_id']} [{a['grade']}] {a['source']}{flag}")
        print(f"  제목: {a['title']}")
        print(f"  요약: {a.get('summary') or PENDING}")
        print(f"  관련성: {a.get('ulsan_relevance') or PENDING}")
        print(f"  tags: {', '.join(a['tags'])}")


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source",
                        help=f"ax-vault-full의 AX뉴스 폴더. 생략하면 환경변수 {selector.SOURCE_ENV}를 사용 "
                             f"(예: {selector.SOURCE_ENV}={selector.SOURCE_EXAMPLE})")
    selector.add_range_args(parser)
    parser.add_argument("--write", action="store_true",
                        help="daily 파일 생성·덧붙이기와 index.md·README.md 갱신을 실제로 수행 (없으면 dry-run)")
    parser.add_argument("--summaries", default=DEFAULT_SUMMARIES,
                        help=f"요약 preview JSON (기본 {DEFAULT_SUMMARIES})")
    parser.add_argument("--allow-missing-summaries", action="store_true",
                        help="summaries에 없는 anchor는 [미작성]으로 둠 (없으면 중단)")
    parser.add_argument("--accept-review", default="",
                        help="review가 남아 있어도 통과시킬 anchor_id (쉼표로 구분, 사람이 확인한 것만)")
    parser.add_argument("--print-preview", action="store_true",
                        help="사람 검토용으로 이번 대상의 제목·출처·요약·관련성을 출력 (URL·본문 제외)")
    parser.add_argument("--limit-ids", type=int, default=20, help="출력할 anchor_id 개수")
    args = parser.parse_args()

    source = resolve_source(args.source)
    published = selector.published_anchor_ids()
    exclude = frozenset() if args.include_published else frozenset(published)
    anchors = collect_anchors(source, args.since, args.on, exclude)
    summaries, review, summary_stats = load_summaries(args.summaries, anchors, args.allow_missing_summaries)
    for a in anchors:
        a.update(summaries.get(a["anchor_id"], {}))
    by_date = collections.defaultdict(list)
    for a in anchors:
        by_date[a["date"]].append(a)

    # 1단계: 모든 파일의 결과를 메모리에서 만든다 (아직 쓰지 않음)
    planned = {}  # date -> (text, added, dup)
    existed = {}  # date -> 쓰기 전에 파일이 있었는지 (보고용)
    for date, items in by_date.items():
        path = DAILY_DIR / f"{date}.md"
        existed[date] = path.exists()
        existing = path.read_text(encoding="utf-8") if path.exists() else ""
        present = set(selector.PUBLISHED_ID_RE.findall(existing))
        for a in items:
            a["_will_add"] = a["anchor_id"] not in present
        if existing:
            planned[date] = append_daily(existing, items)
        else:
            planned[date] = (render_daily(date, items), len(items), 0)

    # 2단계: 중단 조건 검사
    accepted = {x.strip() for x in args.accept_review.split(",") if x.strip()}
    blocking = [f"{aid}: review 남아 있음 ({'; '.join(review[aid])}) - 확인 후 --accept-review {aid}"
                for aid in sorted(a["anchor_id"] for a in anchors if a["_will_add"])
                if aid in review and aid not in accepted]
    blocking += safety_check(planned, anchors, {k: v for k, v in review.items() if k not in accepted},
                             args.allow_missing_summaries, accepted)

    existing_texts = {f.stem: f.read_text(encoding="utf-8") for f in sorted(DAILY_DIR.glob("????-??-??.md"))}
    after = dict(existing_texts, **{d: t for d, (t, _, _) in planned.items()})
    counts_after = daily_counts(after) if after else {}

    # 3단계: 검사를 모두 통과했을 때만 쓴다
    if args.write and not blocking and anchors:
        DAILY_DIR.mkdir(exist_ok=True)
        for date, (text, added, _) in planned.items():
            if added:
                (DAILY_DIR / f"{date}.md").write_text(text, encoding="utf-8", newline="\n")
        new_index, new_readme = updated_index_and_readme(counts_after)
        INDEX_PATH.write_text(new_index, encoding="utf-8", newline="\n")
        README_PATH.write_text(new_readme, encoding="utf-8", newline="\n")

    print_report(anchors, by_date, planned, args.write, args.limit_ids, summary_stats,
                 blocking, counts_after, len(exclude), existed)
    if args.print_preview:
        print_preview(anchors, review)
    if not anchors:
        print("\n신규 anchor가 없습니다. 쓸 것이 없습니다.")
    elif args.write and blocking:
        sys.exit("\n중단: 위 사유를 해결하기 전에는 아무 파일도 쓰지 않았습니다.")
    elif args.write:
        print("\n쓰기 완료: daily 파일, index.md, README.md를 갱신했습니다. commit 전 git diff로 확인하세요.")


if __name__ == "__main__":
    main()
