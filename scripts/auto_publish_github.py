"""
auto-publish 알림 (GitHub Issue). gh CLI와 GH_TOKEN을 쓴다. 표준 라이브러리만 사용.

- hold --report <auto_publish 결과 JSON>: 이번 실행에서 처음 보류된 anchor_id가 있으면 Issue 1건.
  이미 열려 있는 hold Issue에 있는 ID는 다시 올리지 않는다 (보류 앵커는 매일 재시도되므로).
- weekly: 지난 7일 공개 건수(auto-publish 커밋), 품질 보정 공개, 보류 건(hold Issue), 원본 소멸로
  내린 앵커(auto-publish 커밋의 unpublish 줄), 실행 실패 수를 Issue 1건으로 올린다.
- Issue 본문에는 anchor_id·사유 코드·건수·실행 링크만 쓴다.
- --dry-run: Issue를 만들지 않고 제목·본문만 출력한다.
"""
import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone

KST = timezone(timedelta(hours=9))
LABEL_HOLD = "auto-publish-hold"
LABEL_WEEKLY = "auto-publish-weekly"
WORKFLOW = "auto-publish.yml"
COMMIT_PREFIX = "auto-publish"
ID_LINE_RE = re.compile(r"^- `?([0-9a-f]{8})`?\s*(?:—|-)?\s*(.*)$", re.M)
COMMIT_LINE_RE = re.compile(r"^- ([0-9a-f]{8}) daily/\S+(?: \[quality: ([^\]]+)\])?$", re.M)
UNPUBLISH_LINE_RE = re.compile(r"^- unpublish ([0-9a-f]{8}) daily/\S+ \((\w+)\)$", re.M)


def gh(*args) -> str:
    return subprocess.run(["gh", *args], check=True, capture_output=True, text=True, encoding="utf-8").stdout


def run_url() -> str:
    server, repo, rid = (os.environ.get(k) for k in ("GITHUB_SERVER_URL", "GITHUB_REPOSITORY", "GITHUB_RUN_ID"))
    return f"{server}/{repo}/actions/runs/{rid}" if server and repo and rid else ""


def hold_issue(report: dict, already_reported: set):
    """(title, body) | None - 새로 보류된 ID만."""
    new = [h for h in report["held"] if h["id"] not in already_reported]
    if not new:
        return None
    title = f"[auto-publish] 보류 {len(new)}건 ({report['date']})"
    lines = ["자동 공개 조건을 통과하지 못해 공개하지 않은 앵커입니다. (ID와 사유 코드만 기록)", ""]
    lines += [f"- `{h['id']}` — {', '.join(h['codes'])}" for h in new]
    lines += ["", "보류 앵커는 마지막 공개 날짜 기준 7일 동안 매일 다시 시도합니다.",
              "공개하지 않기로 했으면 `config/auto_publish_exclude.txt`에 ID를 추가하고 이 Issue를 닫으세요."]
    if run_url():
        lines += ["", f"실행: {run_url()}"]
    return title, "\n".join(lines) + "\n"


def ids_in_open_hold_issues() -> set:
    issues = json.loads(gh("issue", "list", "--label", LABEL_HOLD, "--state", "open",
                           "--limit", "200", "--json", "body"))
    return {m.group(1) for i in issues for m in ID_LINE_RE.finditer(i.get("body") or "")}


def parse_publish_log(log_text: str):
    """git log 본문들 -> (공개 ID 목록, {ID: 품질 코드}, 원본 소멸로 내린 ID 목록)."""
    published, quality = [], {}
    for m in COMMIT_LINE_RE.finditer(log_text):
        published.append(m.group(1))
        if m.group(2):
            quality[m.group(1)] = m.group(2)
    vanished = [m.group(1) for m in UNPUBLISH_LINE_RE.finditer(log_text) if m.group(2) == "SOURCE_VANISHED"]
    return published, quality, vanished


def weekly_issue(start: datetime, end: datetime, published: list, quality: dict, held: dict,
                 runs_total: int, runs_failed: int, vanished: list = ()):
    title = f"[auto-publish] 주간 요약 {start:%Y-%m-%d} ~ {end:%Y-%m-%d}"
    lines = [f"- 공개: {len(published)}건", f"- 품질 보정 후 공개: {len(quality)}건"]
    lines += [f"  - `{aid}` — {codes}" for aid, codes in sorted(quality.items())]
    lines.append(f"- 보류: {len(held)}건")
    lines += [f"  - `{aid}` — {codes}" for aid, codes in sorted(held.items())]
    lines.append(f"- 원본 소멸로 내림: {', '.join(f'`{aid}`' for aid in vanished) if vanished else '없음'}")
    lines.append(f"- 실행 실패: {'없음' if not runs_failed else f'{runs_failed}회'} (전체 실행 {runs_total}회)")
    return title, "\n".join(lines) + "\n"


def collect_weekly(now: datetime):
    start = now - timedelta(days=7)
    log_text = subprocess.run(
        ["git", "log", f"--since={start.isoformat()}", f"--grep=^{COMMIT_PREFIX} ", "--format=%B"],
        check=True, capture_output=True, text=True, encoding="utf-8").stdout
    published, quality, vanished = parse_publish_log(log_text)
    held = {}
    for i in json.loads(gh("issue", "list", "--label", LABEL_HOLD, "--state", "all", "--limit", "200",
                           "--json", "body,createdAt")):
        if datetime.fromisoformat(i["createdAt"].replace("Z", "+00:00")) >= start:
            for m in ID_LINE_RE.finditer(i.get("body") or ""):
                if m.group(1) not in published:  # 재시도로 나중에 공개된 앵커는 보류에서 뺀다
                    held[m.group(1)] = m.group(2).strip()
    runs = [r for r in json.loads(gh("run", "list", "--workflow", WORKFLOW, "--limit", "100",
                                     "--json", "conclusion,createdAt"))
            if datetime.fromisoformat(r["createdAt"].replace("Z", "+00:00")) >= start]
    failed = sum(1 for r in runs if r.get("conclusion") == "failure")
    return start, published, quality, held, len(runs), failed, vanished


def create_issue(title: str, body: str, label: str, dry_run: bool):
    if dry_run:
        print(f"[dry-run] {title}\n{body}")
        return
    gh("issue", "create", "--title", title, "--body", body, "--label", label)
    print(f"Issue 생성: {title}")


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_hold = sub.add_parser("hold")
    p_hold.add_argument("--report", required=True)
    p_hold.add_argument("--dry-run", action="store_true")
    p_week = sub.add_parser("weekly")
    p_week.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if args.cmd == "hold":
        report = json.loads(open(args.report, encoding="utf-8").read())
        issue = hold_issue(report, ids_in_open_hold_issues())
        if issue is None:
            print("새로 보류된 앵커 없음: Issue를 만들지 않습니다.")
            return
        create_issue(*issue, LABEL_HOLD, args.dry_run)
    else:
        now = datetime.now(KST)
        start, published, quality, held, total, failed, vanished = collect_weekly(now)
        create_issue(*weekly_issue(start, now, published, quality, held, total, failed, vanished),
                     LABEL_WEEKLY, args.dry_run)


if __name__ == "__main__":
    main()
