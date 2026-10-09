"""
ax-vault-full -> public-ax 앵커 후보 1차 dry-run 집계.

- ax-vault-full/AX뉴스 아래 md 파일의 YAML frontmatter만 읽는다 (본문은 읽지 않음).
- 기존 8개 필드(title, date, source, section, grade, industries, url, tags)만 있는
  파일과, 웹앱 분류 필드(region, loc, ulsan_score, core, tech, evidence)가 추가된
  파일을 모두 처리한다. 신규 필드가 없어도 오류 없이 넘어간다.
- 후보를 A(울산 직접) > B1(주력산업·기업, 제목 키워드) > B2(주력산업, industries 값)
  > C(AX 핵심기술) > D(기타) 순으로 분류한다.
- --scope로 선택 범위를 정한다: direct(기본, A - 1차 export 대상) / direct-plus(A+B1,
  2차 검토) / topics(C, topic 문서 후보 분석) / all(A+B1+B2+C+D, 전체 분석).
- 출력은 건수와 anchor_id(파일명 끝 8자리 해시)뿐이다. 제목·URL·본문·요약은
  출력하지 않으며, 어떤 파일도 쓰지 않는다.
"""
import argparse
import collections
import json
import re
import sys
from pathlib import Path

import yaml

DEFAULT_SOURCE = r"C:\Users\minsi\ax-vault-full\AX뉴스"

BASE_FIELDS = ("title", "date", "source", "section", "grade", "industries", "url", "tags")
NEW_FIELDS = ("region", "loc", "ulsan_score", "core", "tech", "evidence")

ANCHOR_ID_RE = re.compile(r"_([0-9a-f]{8})\.md$")
DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")

# --- 제목 키워드 (그룹별) -------------------------------------------------
# A: 울산 직접 - 지역명 + 울산 소재 기관
KW_ULSAN = ["울산", "UNIST", "울산과학기술원", "울산대", "울산대학교"]
# B: 울산 주력산업 - 업종명 + 울산 주력산업 기업
KW_INDUSTRY = ["조선", "자동차", "석유화학", "화학", "에너지", "수소", "배터리"]
KW_INDUSTRY_COMPANY = [
    "현대차", "현대자동차", "현대모비스", "HD현대", "HD현대중공업", "한화오션",
    "SK에너지", "SK이노베이션", "S-OIL", "에쓰오일", "고려아연",
]
# C: AX 핵심기술
KW_AX_TECH = [
    "제조AX", "산업AX", "제조AI", "피지컬AI", "디지털트윈", "자율제조",
    "스마트팩토리", "로봇", "데이터센터", "AIDC",
]
# D: 후보로는 잡지만 A/B/C 어디에도 명확히 속하지 않는 연구기관
KW_OTHER = ["KETI", "생산기술연구원", "한국생산기술연구원"]

INDUSTRY_VALUES = {"조선", "자동차", "에너지", "석유화학", "배터리", "철강·기계"}
TECH_VALUES = ["피지컬AI", "데이터센터", "디지털트윈", "자율제조", "로봇", "LLM", "에이전트"]

GROUP_LABELS = {
    "A": "A  울산 직접 관련",
    "B1": "B1 울산 주력산업·기업 (제목 키워드/core)",
    "B2": "B2 울산 주력산업 (제목 주력산업 키워드 없이 industries 값)",
    "C": "C  AX 핵심기술 참고사례",
    "D": "D  기타 후보",
}
# direct: 1차 export 대상 / direct-plus: 2차 검토 / topics: topic 문서 후보 분석 / all: 전체 분석
SCOPES = {
    "direct": {"A"},
    "direct-plus": {"A", "B1"},
    "topics": {"C"},
    "all": set(GROUP_LABELS),
}
REASONS = ("title_keyword", "industry_match", "region_match", "ulsan_score_match", "core_match", "tech_match")


def norm(s) -> str:
    """공백·가운뎃점·하이픈·밑줄을 지우고 대문자로 - '피지컬 AI' == '피지컬AI', 'S-OIL' == 'SOIL'."""
    return re.sub(r"[\s·\-_]", "", str(s)).upper()


def as_list(v) -> list:
    if v is None or v == "":
        return []
    return [str(x) for x in v] if isinstance(v, list) else [str(v)]


def as_int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def read_frontmatter(path: Path) -> dict:
    """첫 줄 '---'부터 닫는 '---'까지만 읽는다. 본문 줄에는 도달하지 않는다."""
    lines = []
    with path.open(encoding="utf-8", errors="replace") as f:
        if f.readline().strip() != "---":
            return {}
        for line in f:
            if line.strip() == "---":
                break
            lines.append(line)
    try:
        fm = yaml.safe_load("".join(lines))
    except yaml.YAMLError:
        return {}
    return fm if isinstance(fm, dict) else {}


def normalize_date(value, path: Path) -> str:
    # yaml이 ISO 타임스탬프를 datetime으로 바꿔도 str()의 앞 10자리는 YYYY-MM-DD.
    m = DATE_RE.search(str(value)) if value else None
    if m:
        return m.group(1)
    m = DATE_RE.fullmatch(path.parent.name)  # 폴더명 AX뉴스/YYYY/YYYY-MM-DD
    return m.group(1) if m else "unknown"


def title_hits(title_n: str, keywords) -> bool:
    return any(norm(k) in title_n for k in keywords)


def classify(fm: dict):
    """(group or None, reasons) - group None이면 후보 아님."""
    title_n = norm(fm.get("title") or "")
    industries = as_list(fm.get("industries"))
    region = fm.get("region")
    ulsan_score = as_int(fm.get("ulsan_score"))
    core = as_int(fm.get("core"))
    tech_n = [norm(t) for t in as_list(fm.get("tech"))]

    t_ulsan = title_hits(title_n, KW_ULSAN)
    t_industry = title_hits(title_n, KW_INDUSTRY) or title_hits(title_n, KW_INDUSTRY_COMPANY)
    t_tech = title_hits(title_n, KW_AX_TECH)
    t_other = title_hits(title_n, KW_OTHER)
    ind_match = any(i in INDUSTRY_VALUES for i in industries)
    region_match = region == "울산"
    score_match = ulsan_score is not None and ulsan_score > 0
    core_match = core == 1
    tech_match = any(norm(v) in t for v in TECH_VALUES for t in tech_n)

    reasons = []
    if t_ulsan or t_industry or t_tech or t_other:
        reasons.append("title_keyword")
    for name, hit in (("industry_match", ind_match), ("region_match", region_match),
                      ("ulsan_score_match", score_match), ("core_match", core_match),
                      ("tech_match", tech_match)):
        if hit:
            reasons.append(name)
    if not reasons:
        return None, []

    if t_ulsan or region_match or score_match:
        group = "A"
    elif t_industry or core_match:
        group = "B1"
    elif ind_match:
        # 제목에 주력산업·기업 키워드 없이 industries 값으로 B가 된 경우 - 타 지역 기사가
        # 많이 섞인다. (제목에 C 기술 키워드가 함께 있어도 B > C 우선순위상 여기 남는다.)
        group = "B2"
    elif t_tech or tech_match:
        group = "C"
    else:
        group = "D"
    return group, reasons


def run(source: Path, scope: str) -> dict:
    files = sorted(source.rglob("*.md"))
    selected_groups = SCOPES[scope]
    stats = {
        "scope": scope,
        "total_md": len(files),
        "base_only": 0,
        "with_new_fields": 0,
        "no_frontmatter": 0,
        "candidates": 0,
        "by_group": collections.Counter({g: 0 for g in GROUP_LABELS}),
        "selected": 0,
        # 아래 by_* 와 candidate_ids는 scope 적용 후 선택분 기준
        "by_date": collections.Counter(),
        "by_section": collections.Counter(),
        "by_grade": collections.Counter(),
        "by_industries": collections.Counter(),
        "by_reason": collections.Counter({r: 0 for r in REASONS}),
    }
    candidate_ids = []  # (date, anchor_id)

    for path in files:
        fm = read_frontmatter(path)
        if not fm:
            stats["no_frontmatter"] += 1
            continue
        if any(k in fm for k in NEW_FIELDS):
            stats["with_new_fields"] += 1
        else:
            stats["base_only"] += 1

        group, reasons = classify(fm)
        if group is None:
            continue
        m = ANCHOR_ID_RE.search(path.name)
        anchor_id = m.group(1) if m else "no-id"
        date = normalize_date(fm.get("date"), path)

        stats["candidates"] += 1
        stats["by_group"][group] += 1
        if group not in selected_groups:
            continue
        stats["selected"] += 1
        stats["by_date"][date] += 1
        stats["by_section"][str(fm.get("section") or "(없음)")] += 1
        stats["by_grade"][str(fm.get("grade") or "(없음)")] += 1
        for ind in as_list(fm.get("industries")) or ["(없음)"]:
            stats["by_industries"][ind] += 1
        stats["by_reason"].update(reasons)
        candidate_ids.append((date, anchor_id))

    candidate_ids.sort(key=lambda x: (x[0], x[1]), reverse=True)  # 최신 날짜 먼저
    stats["candidate_ids"] = [aid for _, aid in candidate_ids]
    return stats


def print_report(stats: dict, limit_ids: int):
    def table(title, counter, keys=None):
        print(title)
        items = [(k, counter[k]) for k in keys] if keys else counter.most_common()
        for k, v in items:
            print(f"  {v:5d}  {k}")

    scope = stats["scope"]
    print("[dry-run] 파일을 쓰지 않습니다. 제목·URL·본문은 출력하지 않습니다.\n")
    print(f"1. scope: {scope} (선택 그룹: {', '.join(g for g in GROUP_LABELS if g in SCOPES[scope])})")
    print(f"2. 전체 md 파일 수: {stats['total_md']}"
          f"  (기존 8개 필드만 {stats['base_only']} / 신규 필드 포함 {stats['with_new_fields']})")
    if stats["no_frontmatter"]:
        print(f"   (frontmatter를 읽지 못한 파일: {stats['no_frontmatter']})")
    print(f"3. 전체 후보 수: {stats['candidates']}")
    print(f"4. scope 적용 후 선택 수: {stats['selected']}")
    print("5. 그룹별 전체 후보 수 (* = 이번 scope에 포함)")
    for g, label in GROUP_LABELS.items():
        mark = "*" if g in SCOPES[scope] else " "
        print(f"  {mark}{stats['by_group'][g]:5d}  {label}")
    table("6. 날짜별 선택 수", stats["by_date"], sorted(stats["by_date"]))
    table("7. section별 선택 수", stats["by_section"])
    table("8. grade별 선택 수", stats["by_grade"])
    table("9. industries별 선택 수", stats["by_industries"])
    table("   (참고) 선택분의 필터 사유별 건수 - 한 기사에 여러 사유 가능", stats["by_reason"], REASONS)
    ids = stats["candidate_ids"][:limit_ids]
    print(f"10. 선택 anchor_id {len(ids)}개 (최신 날짜순)")
    for aid in ids:
        print(f"  {aid}")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source", default=DEFAULT_SOURCE, help="ax-vault-full의 AX뉴스 폴더")
    parser.add_argument("--scope", choices=list(SCOPES), default="direct",
                        help="direct=A(기본, 1차 export) / direct-plus=A+B1 / topics=C / all=전체 분석")
    parser.add_argument("--limit-ids", type=int, default=20, help="출력할 후보 anchor_id 개수")
    parser.add_argument("--json", action="store_true", help="JSON 요약으로 출력")
    args = parser.parse_args()

    sys.stdout.reconfigure(encoding="utf-8")
    source = Path(args.source)
    if not source.is_dir():
        sys.exit(f"source 폴더가 없습니다: {source}")

    stats = run(source, args.scope)
    if args.json:
        out = {k: (dict(v) if isinstance(v, collections.Counter) else v) for k, v in stats.items()}
        out["candidate_ids"] = stats["candidate_ids"][:args.limit_ids]
        print(json.dumps(out, ensure_ascii=False, indent=2))
    else:
        print_report(stats, args.limit_ids)


if __name__ == "__main__":
    main()
