"""
공개된 앵커 하나를 내린다: python scripts/unpublish_anchor.py <anchor_id> [--write]

1. daily/ 파일에서 그 앵커 블록을 지운다 (다른 블록은 한 글자도 바꾸지 않고 번호만 다시 매김).
2. anchor_count를 다시 계산한다. 남은 블록이 없으면 그 날짜 파일을 지운다.
3. index.md "일자별 앵커" 표와 README.md 운영 현황 줄을 daily/ 전체 기준으로 다시 만든다.
4. config/auto_publish_exclude.txt에 ID를 등록해 자동·수동 갱신이 다시 고르지 않게 한다.

기본은 dry-run(계획만 출력). --write일 때만 쓴다. 출력은 anchor_id·파일명·건수만.
"""
import argparse
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import anchor_safety as safety  # noqa: E402
import export_direct_anchors as exporter  # noqa: E402

selector = exporter.selector
KST = timezone(timedelta(hours=9))
BLOCK_SPLIT_RE = re.compile(r"(?m)^(?=### \d+\. )")
BLOCK_NUM_RE = re.compile(r"^### \d+\. ")


def remove_block(text: str, anchor_id: str):
    """(새 텍스트 | None(블록이 하나도 안 남음), 지웠는지)."""
    head, *blocks = BLOCK_SPLIT_RE.split(text)
    keep = [b for b in blocks if f"\n- 앵커 ID: {anchor_id}\n" not in b]
    if len(keep) == len(blocks):
        return text, False
    if not keep:
        return None, True
    keep = [BLOCK_NUM_RE.sub(f"### {i}. ", b, count=1) for i, b in enumerate(keep, 1)]
    new = (head + "".join(keep)).rstrip("\n") + "\n"
    new = exporter.ANCHOR_COUNT_RE.sub(f"anchor_count: {len(keep)}", new, count=1)
    return new, True


def add_exclude(path: Path, anchor_id: str, today: str, reason: str = "") -> bool:
    if anchor_id in selector.excluded_anchor_ids(path):
        return False
    path.parent.mkdir(exist_ok=True)
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    if text and not text.endswith("\n"):
        text += "\n"
    note = f"unpublished {today}" + (f" {reason}" if reason else "")
    path.write_text(text + f"{anchor_id}  # {note}\n", encoding="utf-8", newline="\n")
    return True


def unpublish(anchor_id: str, repo_root: Path, write: bool, today: str = None) -> int:
    daily_dir = repo_root / "daily"
    today = today or datetime.now(KST).date().isoformat()
    exclude_path = repo_root / "config" / "auto_publish_exclude.txt"
    mode = "WRITE" if write else "dry-run (파일을 쓰지 않습니다)"
    print(f"[{mode}] unpublish {anchor_id}")

    hits = [f for f in sorted(daily_dir.glob("????-??-??.md"))
            if anchor_id in selector.PUBLISHED_ID_RE.findall(f.read_text(encoding="utf-8"))]
    if not hits:
        print(f"  daily/에 {anchor_id}가 없습니다.")
    texts = {f.stem: f.read_text(encoding="utf-8") for f in sorted(daily_dir.glob("????-??-??.md"))}
    changes = {}
    for f in hits:
        new, _ = remove_block(texts[f.stem], anchor_id)
        changes[f] = new
        if new is None:
            texts.pop(f.stem)
            print(f"  daily/{f.name}: 블록 제거 → 남은 앵커 0건, 파일 삭제")
        else:
            problems = safety.daily_text_problems(new)
            if problems:
                print(f"  daily/{f.name}: 제거 후 검사 실패 {len(problems)}건 - 중단")
                return 1
            texts[f.stem] = new
            print(f"  daily/{f.name}: 블록 제거 → anchor_count {exporter.ANCHOR_COUNT_RE.search(new).group(1)}")
    counts = exporter.daily_counts(texts)
    print(f"  반영 후: 파일 {len(counts)}개, 앵커 {sum(counts.values())}건")
    already = anchor_id in selector.excluded_anchor_ids(exclude_path)
    print(f"  exclude 등록: {'이미 있음' if already else 'config/auto_publish_exclude.txt에 추가'}")
    if not write:
        return 0
    for f, new in changes.items():
        if new is None:
            f.unlink()
        else:
            f.write_text(new, encoding="utf-8", newline="\n")
    if changes and counts:
        new_index, new_readme = exporter.updated_index_and_readme(counts, repo_root / "index.md",
                                                                  repo_root / "README.md")
        (repo_root / "index.md").write_text(new_index, encoding="utf-8", newline="\n")
        (repo_root / "README.md").write_text(new_readme, encoding="utf-8", newline="\n")
    add_exclude(exclude_path, anchor_id, today)
    print("쓰기 완료. git diff로 확인한 뒤 commit/push 하세요.")
    return 0


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("anchor_id", help="8자리 anchor_id")
    parser.add_argument("--write", action="store_true", help="실제로 쓴다 (없으면 dry-run)")
    args = parser.parse_args()
    if not re.fullmatch(r"[0-9a-f]{8}", args.anchor_id):
        sys.exit("anchor_id는 8자리 16진수여야 합니다.")
    sys.exit(unpublish(args.anchor_id, exporter.REPO_ROOT, args.write))


if __name__ == "__main__":
    main()
