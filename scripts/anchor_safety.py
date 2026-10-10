"""
public-ax 공개 안전성 검사 (generate_direct_anchor_summaries.py, export_direct_anchors.py 공용).

- 원문 복사 검사: 생성 문장이 기사 본문과 COPY_MAX_RUN자 이상 연속으로 같으면 실패.
- daily 파일 검사: 모든 줄이 템플릿에 정해진 형태 중 하나여야 한다. 그 밖의 줄(기사 본문
  문장, 내부 메모 등)이 하나라도 있으면 실패. private 원문 위치는 ax-vault-full/AX뉴스/...
  형식만 허용하고, 로컬 경로(C:\\, /Users/ 등)나 review 메모 문구가 있으면 실패.
"""
import difflib
import re
from pathlib import Path

COPY_MAX_RUN = 30  # 원문과 연속으로 같은 글자 수(공백 정규화 후)가 이 값 이상이면 복사로 본다
SUMMARY_MAX_CHARS = 200
RELEVANCE_MAX_CHARS = 150
PENDING = "[미작성]"

PRIVATE_PATH_RE = re.compile(r"^ax-vault-full/AX뉴스/\d{4}/\d{4}-\d{2}-\d{2}/[^/\\]+_[0-9a-f]{8}\.md$")
# 드라이브 문자는 앞에 글자가 없을 때만 (https:// 의 "s:/"를 드라이브로 오인하지 않도록)
LOCAL_PATH_RE = re.compile(r"(?<![A-Za-z])[A-Za-z]:[\\/]|/Users/|/home/|\\Users\\|AppData", re.I)

# daily 파일에 나올 수 있는 줄의 형태 (export_direct_anchors.render_daily와 맞춘다)
ALLOWED_LINE_RES = [re.compile(p) for p in (
    r"^---$",
    r"^(date|source_system|source_vault|scope|anchor_count): \S.*$",
    r"^$",
    r"^# \d{4}-\d{2}-\d{2} AX direct anchors$",
    r"^> korea-industry-ax 수록 기사 중 울산 직접 관련성이 높은 공개 앵커입니다\. 기사 전문은 포함하지 않습니다\.$",
    r"^## 앵커 목록$",
    r"^### \d+\. .+$",
    r"^- (앵커 ID|날짜|출처|원문 URL|수집 등급|section|industries|짧은 사실 요약|울산 AX 관련성|private 원문 위치): ?.*$",
    r"^- tags:$",
    r"^  - \S+$",
)]


def read_body(path: Path) -> str:
    """frontmatter 뒤의 본문. export_to_vault.py가 쓰는 '# 제목'과 '출처:' 줄은 뺀다."""
    text = path.read_text(encoding="utf-8", errors="replace")
    if text.startswith("---"):
        end = text.find("\n---", 3)
        text = text[end + 4:] if end != -1 else text
    lines = [l for l in text.splitlines() if not l.startswith("# ") and not l.startswith("출처:")]
    return "\n".join(lines).strip()


def squash(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def longest_copy_run(generated: str, body: str) -> int:
    a, b = squash(body), squash(generated)
    if not a or not b:
        return 0
    m = difflib.SequenceMatcher(None, a, b, autojunk=False).find_longest_match(0, len(a), 0, len(b))
    return m.size


def sentence_count(s: str) -> int:
    return len([p for p in re.split(r"(?<=[.!?。])\s+", s.strip()) if p])


def text_problems(summary: str, relevance: str, body: str) -> list:
    """요약·관련성 문장 자체의 검사 (길이·문장 수·원문 복사)."""
    problems = []
    if not summary.strip():
        problems.append("summary가 비어 있음")
    if not relevance.strip():
        problems.append("ulsan_relevance가 비어 있음")
    if summary and sentence_count(summary) > 2:
        problems.append(f"summary가 {sentence_count(summary)}문장 (최대 2문장)")
    if len(summary) > SUMMARY_MAX_CHARS:
        problems.append(f"summary가 {len(summary)}자 (최대 {SUMMARY_MAX_CHARS}자)")
    for name, text in (("summary", summary), ("ulsan_relevance", relevance)):
        run = longest_copy_run(text, body)
        if run >= COPY_MAX_RUN:
            problems.append(f"{name}가 원문과 {run}자 연속으로 같음 (최대 {COPY_MAX_RUN - 1}자)")
    return problems


def daily_text_problems(text: str, review_notes=(), allow_pending: bool = False) -> list:
    """렌더링된 daily 파일 전체 검사. 문제 줄의 '번호와 종류'만 돌려준다 (내용은 돌려주지 않음)."""
    problems = []
    for n, line in enumerate(text.splitlines(), 1):
        if not any(r.match(line) for r in ALLOWED_LINE_RES):
            problems.append(f"{n}행: 템플릿 밖의 줄 (본문·메모 유입 의심)")
        if line.startswith("- private 원문 위치: "):
            if not PRIVATE_PATH_RE.match(line.split(": ", 1)[1]):
                problems.append(f"{n}행: private 원문 위치 형식이 아님")
        elif LOCAL_PATH_RE.search(line):
            problems.append(f"{n}행: 로컬 경로로 보이는 문자열")
        if PENDING in line and not allow_pending:
            problems.append(f"{n}행: {PENDING} 남아 있음")
    for note in review_notes:
        if note and note in text:
            problems.append("review 메모 문구가 들어 있음")
            break
    return problems
