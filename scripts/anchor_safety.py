"""
public-ax 공개 안전성 검사 (generate_direct_anchor_summaries.py, export_direct_anchors.py 공용).

- 원문 복사 검사: 생성 문장이 기사 본문과 COPY_MAX_RUN자 이상 연속으로 같으면 실패.
  50자인 이유: AX 기사는 영문 약어 + 풀이 + 한국어 대응어 조합이 많아 고유명칭만으로
  40자를 넘는 경우가 많다.
- daily 파일 검사: 모든 줄이 템플릿에 정해진 형태 중 하나여야 한다. 그 밖의 줄(기사 본문
  문장, 내부 메모 등)이 하나라도 있으면 실패. private 원문 위치는 ax-vault-full/AX뉴스/...
  형식만 허용하고, 로컬 경로(C:\\, /Users/ 등)나 review 메모 문구가 있으면 실패.
- *_issues 함수는 사유 코드가 붙은 튜플을, *_problems 함수는 수동 CLI용 한국어 메시지를
  돌려준다. 둘 다 검사 대상 문장 내용은 넣지 않는다. 자동 공개(auto_publish.py)는 코드만 쓴다.
"""
import difflib
import re
from pathlib import Path

COPY_MAX_RUN = 50  # 원문과 연속으로 같은 글자 수(공백 정규화 후)가 이 값 이상이면 복사로 본다
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


def split_sentences(s: str) -> list:
    return [p for p in re.split(r"(?<=[.!?。])\s+", s.strip()) if p]


def sentence_count(s: str) -> int:
    return len(split_sentences(s))


def truncate_sentences(s: str, max_sentences: int, max_chars: int):
    """앞에서부터 문장 단위로 max_sentences문장·max_chars자 안에 들어가는 만큼만 남긴다.
    첫 문장 하나만으로 max_chars를 넘으면 None (문장 중간에서는 자르지 않는다)."""
    sents = split_sentences(squash(s))
    if not sents or len(sents[0]) > max_chars:
        return None
    out = []
    for sent in sents[:max_sentences]:
        if len(" ".join(out + [sent])) > max_chars:
            break
        out.append(sent)
    return " ".join(out)


def text_issues(summary: str, relevance: str, body: str) -> list:
    """요약·관련성 문장 자체의 검사 (길이·문장 수·원문 복사). [(코드, 필드, 메시지)]"""
    issues = []
    if not summary.strip():
        issues.append(("SUMMARY_EMPTY", "summary", "summary가 비어 있음"))
    if not relevance.strip():
        issues.append(("SUMMARY_EMPTY", "relevance", "ulsan_relevance가 비어 있음"))
    if summary and sentence_count(summary) > 2:
        issues.append(("TOO_MANY_SENTENCES", "summary", f"summary가 {sentence_count(summary)}문장 (최대 2문장)"))
    if len(summary) > SUMMARY_MAX_CHARS:
        issues.append(("TOO_LONG", "summary", f"summary가 {len(summary)}자 (최대 {SUMMARY_MAX_CHARS}자)"))
    for field, name, text in (("summary", "summary", summary), ("relevance", "ulsan_relevance", relevance)):
        run = longest_copy_run(text, body)
        if run >= COPY_MAX_RUN:
            issues.append(("COPY_RUN", field, f"{name}가 원문과 {run}자 연속으로 같음 (최대 {COPY_MAX_RUN - 1}자)"))
    return issues


def text_problems(summary: str, relevance: str, body: str) -> list:
    """요약·관련성 문장 자체의 검사 (길이·문장 수·원문 복사)."""
    return [msg for _, _, msg in text_issues(summary, relevance, body)]


def daily_text_issues(text: str, review_notes=(), allow_pending: bool = False) -> list:
    """렌더링된 daily 파일 전체 검사. [(줄 번호 | None, 코드, 메시지)] - 줄 내용은 돌려주지 않음."""
    issues = []
    for n, line in enumerate(text.splitlines(), 1):
        if not any(r.match(line) for r in ALLOWED_LINE_RES):
            issues.append((n, "TEMPLATE_LINE", f"{n}행: 템플릿 밖의 줄 (본문·메모 유입 의심)"))
        if line.startswith("- private 원문 위치: "):
            if not PRIVATE_PATH_RE.match(line.split(": ", 1)[1]):
                issues.append((n, "PRIVATE_PATH_FORMAT", f"{n}행: private 원문 위치 형식이 아님"))
        elif LOCAL_PATH_RE.search(line):
            issues.append((n, "LOCAL_PATH", f"{n}행: 로컬 경로로 보이는 문자열"))
        if PENDING in line and not allow_pending:
            issues.append((n, "PENDING_LEFT", f"{n}행: {PENDING} 남아 있음"))
    for note in review_notes:
        if note and note in text:
            issues.append((None, "REVIEW_NOTE_LEAK", "review 메모 문구가 들어 있음"))
            break
    return issues


def daily_text_problems(text: str, review_notes=(), allow_pending: bool = False) -> list:
    """렌더링된 daily 파일 전체 검사. 문제 줄의 '번호와 종류'만 돌려준다 (내용은 돌려주지 않음)."""
    return [msg for _, _, msg in daily_text_issues(text, review_notes, allow_pending)]
