"""
ax-vault-full -> public-ax daily 앵커 exporter (scope: direct 고정).

- 후보 선별은 dry_run_select_anchors.py의 frontmatter 읽기·분류 로직을 그대로 쓴다.
  scope는 direct(A그룹, 울산 직접 관련)로 고정이다.
- 기본 실행은 dry-run이다. 파일을 쓰지 않고 건수·생성 예정 경로·anchor_id만 출력한다.
- --write를 줬을 때만 daily/YYYY-MM-DD.md를 만든다. 같은 날짜 파일이 이미 있으면
  건너뛰고, --overwrite를 함께 줬을 때만 덮어쓴다.
- daily 파일에는 제목·언론사·날짜·URL·분류값·public-ax tags·private 원문 위치만 쓴다.
  기사 본문은 읽지도 쓰지도 않는다. 짧은 사실 요약과 울산 AX 관련성은 [미작성]으로 둔다.
- 콘솔에는 제목·URL·본문을 출력하지 않는다.
"""
import argparse
import collections
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dry_run_select_anchors as selector  # noqa: E402

SCOPE = "direct"
REPO_ROOT = Path(__file__).resolve().parent.parent
DAILY_DIR = REPO_ROOT / "daily"
VAULT_PREFIX = "ax-vault-full/AX뉴스"
PENDING = "[미작성]"

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


def collect_anchors(source: Path) -> list:
    selected_groups = selector.SCOPES[SCOPE]
    anchors = []
    for path in sorted(source.rglob("*.md")):
        fm = selector.read_frontmatter(path)
        if not fm:
            continue
        group, _ = selector.classify(fm)
        if group not in selected_groups:
            continue
        m = selector.ANCHOR_ID_RE.search(path.name)
        anchors.append({
            "anchor_id": m.group(1) if m else "no-id",
            "date": selector.normalize_date(fm.get("date"), path),
            "title": str(fm.get("title") or "").strip(),
            "source": str(fm.get("source") or "").strip(),
            "url": str(fm.get("url") or "").strip(),
            "grade": str(fm.get("grade") or "").strip(),
            "section": str(fm.get("section") or "").strip(),
            "industries": selector.as_list(fm.get("industries")),
            "tags": build_tags(fm),
            "private_path": f"{VAULT_PREFIX}/{path.relative_to(source).as_posix()}",
        })
    anchors.sort(key=lambda a: (a["date"], GRADE_ORDER.get(a["grade"], 9), a["anchor_id"]))
    return anchors


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
        lines += [
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
            f"- 짧은 사실 요약: {PENDING}",
            f"- 울산 AX 관련성: {PENDING}",
            f"- private 원문 위치: {a['private_path']}",
        ]
    return "\n".join(lines) + "\n"


def print_report(anchors: list, by_date: dict, plan: list, write: bool, limit_ids: int):
    def table(title, counter):
        print(title)
        for k, v in counter.most_common():
            print(f"  {v:5d}  {k}")

    mode = "WRITE" if write else "dry-run (파일을 쓰지 않습니다)"
    print(f"[{mode}] scope={SCOPE}. 제목·URL·본문은 출력하지 않습니다.\n")
    print(f"1. 선택된 anchor 수: {len(anchors)}")
    print(f"2. 생성 예정 daily 파일 수: {len(by_date)}")
    print("3. 날짜별 anchor 수")
    for date in sorted(by_date):
        print(f"  {len(by_date[date]):5d}  {date}")
    table("4. section별 anchor 수", collections.Counter(a["section"] or "(없음)" for a in anchors))
    table("5. grade별 anchor 수", collections.Counter(a["grade"] or "(없음)" for a in anchors))
    table("6. industries별 anchor 수",
          collections.Counter(i for a in anchors for i in (a["industries"] or ["(없음)"])))
    print("7. 생성 예정 파일 경로")
    for rel, n, status in plan:
        print(f"  {rel}  ({n}건)  {status}")
    ids = [a["anchor_id"] for a in sorted(anchors, key=lambda a: (a["date"], a["anchor_id"]), reverse=True)]
    print(f"8. anchor_id {min(limit_ids, len(ids))}개 (최신 날짜순)")
    for aid in ids[:limit_ids]:
        print(f"  {aid}")


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source",
                        help=f"ax-vault-full의 AX뉴스 폴더. 생략하면 환경변수 {selector.SOURCE_ENV}를 사용 "
                             f"(예: {selector.SOURCE_ENV}={selector.SOURCE_EXAMPLE})")
    parser.add_argument("--write", action="store_true", help="daily/YYYY-MM-DD.md 파일을 실제로 생성 (없으면 dry-run)")
    parser.add_argument("--overwrite", action="store_true", help="--write와 함께: 이미 있는 날짜 파일도 덮어씀")
    parser.add_argument("--limit-ids", type=int, default=20, help="출력할 anchor_id 개수")
    args = parser.parse_args()
    if args.overwrite and not args.write:
        parser.error("--overwrite는 --write와 함께만 쓸 수 있습니다.")

    source = resolve_source(args.source)
    anchors = collect_anchors(source)
    by_date = collections.defaultdict(list)
    for a in anchors:
        by_date[a["date"]].append(a)

    plan = []  # (상대경로, 건수, 상태)
    for date in sorted(by_date):
        path = DAILY_DIR / f"{date}.md"
        rel = path.relative_to(REPO_ROOT).as_posix()
        exists = path.exists()
        if not args.write:
            status = "이미 있음 - --write 시 건너뜀 (--overwrite 필요)" if exists else "신규 예정"
        elif exists and not args.overwrite:
            status = "이미 있음 - 건너뜀"
        else:
            DAILY_DIR.mkdir(exist_ok=True)
            path.write_text(render_daily(date, by_date[date]), encoding="utf-8", newline="\n")
            status = "덮어씀" if exists else "생성함"
        plan.append((rel, len(by_date[date]), status))

    print_report(anchors, by_date, plan, args.write, args.limit_ids)


if __name__ == "__main__":
    main()
