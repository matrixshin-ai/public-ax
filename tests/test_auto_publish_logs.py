"""
자동 공개 로그 규칙 검증: 공개 로그(stdout·stderr), 결과 JSON, 커밋 메시지, Issue 본문에
기사 제목·URL·본문, 원문 일치 문장, 생성 요약·관련성 문장, API 오류 원문이 나오지 않아야 한다.
가짜 vault와 가짜 모델 클라이언트를 쓰므로 네트워크·API 키가 필요 없다.
"""
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import anthropic
import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import anchor_safety as safety  # noqa: E402
import auto_publish  # noqa: E402
import auto_publish_github as notify  # noqa: E402
import export_direct_anchors as exporter  # noqa: E402
import unpublish_anchor  # noqa: E402

DATE = "2026-10-12"
PUBLISHED_DATE = "2026-10-10"

BODY_FILLER = ("현장 관계자는 이번 사업이 지역 제조업 경쟁력을 끌어올릴 것으로 기대한다고 밝혔다. "
               "회사는 내년 상반기까지 생산 라인 전체에 같은 방식을 확대 적용할 계획이다.")

# anchor_id -> (제목, 본문 앞부분, 모델 동작)
CASES = {
    "a0000001": ("울산 조선소 용접 로봇 도입 첫번째", "울산 동구 한 조선소가 용접 공정에 협동로봇 스무 대를 투입해 작업 시간을 크게 줄였다.", "good"),
    "a0000002": ("울산 석유화학 공장 디지털트윈 두번째", "울산 남구 석유화학 단지의 한 공장이 설비 전체를 가상공간에 옮긴 디지털트윈 시스템을 가동하기 시작했다.", "copy"),
    "a0000003": ("울산 자동차 부품사 AI 검사 세번째", "울산 북구 자동차 부품 협력사들이 영상 인공지능 기반 품질 검사 장비를 공동으로 구매하기로 했다.", "refusal"),
    "a0000004": ("울산 수소 충전 인프라 확대 네번째", "울산시는 수소 트럭 충전소 다섯 곳을 추가로 짓는 사업에 국비를 확보했다고 발표했다.", "error400"),
    "a0000005": ("울산 데이터센터 유치 협약 다섯번째", "울산시와 한 통신사가 인공지능 데이터센터 건립을 위한 업무협약을 맺고 부지 검토에 들어갔다.", "three"),
    "a0000006": ("울산 배터리 소재 공장 증설 여섯번째", "울산 울주군 배터리 소재 공장이 생산 능력을 두 배로 늘리는 증설 공사를 시작했다.", "longfirst"),
    "a0000007": ("울산 스마트팩토리 지원 일곱번째", "울산 중소 제조기업 서른 곳이 스마트팩토리 고도화 지원 사업 대상으로 새로 선정됐다.", "newline"),
    "a0000008": ("울산 산업AX 인재양성 여덟번째", "울산 지역 대학과 기업이 산업 인공지능 전환 실무 인재를 함께 길러내는 교육 과정을 열었다.", "badlabel"),
    "a0000009": ("울산 C:\\temp 로컬 경로 아홉번째", "울산 한 기업의 사례를 다룬 기사로 제목에 로컬 경로처럼 보이는 문자열이 들어 있다.", "good"),
    "a000000a": ("울산 공개 철회된 기사 열번째", "울산에서 있었던 일을 다룬 기사지만 공개를 철회해 다시 고르지 않아야 한다.", "good"),
}
EXCLUDED_ID = "a000000a"
ERROR_MESSAGE = "요청 거절 사유에 원문이 섞임: " + CASES["a0000004"][1]

GOOD = {
    "a0000001": "동구 조선소가 협동로봇을 용접 작업에 넣어 공정 시간을 단축했다.",
    "a0000005": "시와 통신사가 AI 데이터센터 건립 협약을 맺었다. 부지 검토가 시작됐다. 착공 시점은 미정이다.",
    "a0000006": "가" * 230 + ".",
    "a0000007": "중소 제조기업 30곳이 고도화 지원 대상이 됐다.\n지원은 연말까지 이어진다.",
    "a0000008": "지역 대학과 기업이 산업 AI 전환 실무 교육 과정을 공동 개설했다.",
    "a0000009": "한 기업 사례를 소개한 기사다.",
}
REASON = "울산 제조 현장의 AX 적용 사례로 참고할 수 있다."


def body_of(aid):
    return CASES[aid][1] + " " + BODY_FILLER


class FakeClient:
    def __init__(self):
        self.calls = {}
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self.create))

    def create(self, **params):
        content = params["messages"][0]["content"]
        aid = next(a for a, (_, lead, _) in CASES.items() if lead in content)
        self.calls[aid] = self.calls.get(aid, 0) + 1
        mode = CASES[aid][2]
        if mode == "refusal":
            return SimpleNamespace(stop_reason="refusal", stop_details=SimpleNamespace(category="cyber"), content=[])
        if mode == "error400":
            request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
            raise anthropic.BadRequestError(ERROR_MESSAGE, response=httpx.Response(400, request=request), body=None)
        summary = body_of(aid)[:80] if mode == "copy" else GOOD[aid]
        label = "기타" if mode == "badlabel" else "울산 직접 관련"
        out = {"summary": summary, "relevance_type": label, "relevance_reason": REASON}
        return SimpleNamespace(stop_reason="end_turn", stop_details=None,
                               content=[SimpleNamespace(type="text", text=json.dumps(out, ensure_ascii=False))])


def make_vault(tmp_path: Path) -> Path:
    source = tmp_path / "vault" / "AX뉴스"
    folder = source / "2026" / DATE
    folder.mkdir(parents=True)
    for n, (aid, (title, _, _)) in enumerate(CASES.items(), 1):
        fm = (f"---\ntitle: '{title}'\ndate: {DATE}\nsource: 테스트일보\nsection: 기업·현장\ngrade: A\n"
              f"industries:\n- 조선\nurl: https://example.com/news/{aid}\nregion: 울산\n---\n")
        (folder / f"기사{n}_{aid}.md").write_text(fm + f"# {title}\n출처: 테스트일보\n\n{body_of(aid)}\n",
                                                encoding="utf-8")
    return source


def make_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    (repo / "daily").mkdir(parents=True)
    (repo / "config").mkdir()
    (repo / "config" / "auto_publish_exclude.txt").write_text(f"# 주석\n{EXCLUDED_ID}  # unpublished\n",
                                                               encoding="utf-8")
    old = {"anchor_id": "b0000001", "date": PUBLISHED_DATE, "title": "이미 공개된 앵커", "source": "테스트일보",
           "url": "https://example.com/old", "grade": "A", "section": "기업·현장", "industries": ["조선"],
           "tags": ["울산"], "summary": "이미 공개된 요약이다.", "ulsan_relevance": "울산 직접 관련: 참고.",
           "private_path": f"ax-vault-full/AX뉴스/2026/{PUBLISHED_DATE}/기존_b0000001.md"}
    (repo / "daily" / f"{PUBLISHED_DATE}.md").write_text(exporter.render_daily(PUBLISHED_DATE, [old]),
                                                         encoding="utf-8", newline="\n")
    (repo / "index.md").write_text("# 목차\n\n## 일자별 앵커\n\n(이전)\n\n## 운영 원칙\n\n- 원칙\n", encoding="utf-8")
    (repo / "README.md").write_text("# public-ax\n\n- 운영 현황: (이전)\n", encoding="utf-8")
    return repo


def forbidden_strings() -> list:
    out = [ERROR_MESSAGE, REASON]
    for aid, (title, _, _) in CASES.items():
        out += [title, f"https://example.com/news/{aid}"]
        body = body_of(aid)
        out += [body[i:i + 12] for i in range(0, len(body) - 12, 4)]  # 본문 조각
    for s in GOOD.values():
        out += [p for p in safety.split_sentences(safety.squash(s)) if len(p) >= 8]
    return out


def assert_no_leak(text: str):
    leaked = [s for s in forbidden_strings() if s in text]
    assert not leaked, f"공개 로그에 기사·요약 내용 {len(leaked)}건 유출"


@pytest.fixture
def published(tmp_path, capsys):
    source, repo = make_vault(tmp_path), make_repo(tmp_path)
    client = FakeClient()
    report_path, msg_path = tmp_path / "report.json", tmp_path / "commit.txt"
    rc = auto_publish.main(["--source", str(source), "--repo-root", str(repo), "--today", "2026-10-17",
                            "--write", "--report", str(report_path), "--commit-message", str(msg_path)],
                           client=client)
    captured = capsys.readouterr()
    report = json.loads(report_path.read_text(encoding="utf-8"))
    return SimpleNamespace(rc=rc, out=captured.out + captured.err, report=report, client=client, repo=repo,
                           source=source, msg=msg_path.read_text(encoding="utf-8"), tmp=tmp_path)


def test_logs_report_commit_message_have_no_article_content(published):
    assert published.rc == 0
    assert_no_leak(published.out)
    assert_no_leak(json.dumps(published.report, ensure_ascii=False))
    assert_no_leak(published.msg)
    title, body = notify.hold_issue(published.report, set())
    assert_no_leak(title + body)


def test_publish_and_hold_decisions(published):
    pub = {p["id"]: p for p in published.report["published"]}
    held = {h["id"]: h["codes"] for h in published.report["held"]}
    assert set(pub) == {"a0000001", "a0000005", "a0000007", "a0000008"}
    assert held == {
        "a0000002": ["COPY_RUN:summary"],
        "a0000003": ["SUMMARY_REFUSAL"],
        "a0000004": ["SUMMARY_API_ERROR"],
        "a0000006": ["FIRST_SENTENCE_TOO_LONG:summary"],
        "a0000009": ["LOCAL_PATH"],
    }
    assert pub["a0000005"]["quality"] == ["TOO_MANY_SENTENCES:summary"]
    assert pub["a0000008"]["quality"] == ["RELEVANCE_LABEL:relevance"]
    assert pub["a0000001"]["quality"] == [] and pub["a0000007"]["quality"] == []
    assert EXCLUDED_ID not in pub and EXCLUDED_ID not in held and EXCLUDED_ID not in published.client.calls
    assert published.client.calls["a0000002"] == 3  # COPY_RUN은 3회 재생성 후 보류


def test_written_files(published):
    daily = (published.repo / "daily" / f"{DATE}.md").read_text(encoding="utf-8")
    assert safety.daily_text_problems(daily) == []
    for aid in ("a0000001", "a0000005", "a0000007", "a0000008"):
        assert f"- 앵커 ID: {aid}" in daily
    for aid in ("a0000002", "a0000003", "a0000004", "a0000006", "a0000009", EXCLUDED_ID):
        assert aid not in daily
    assert "anchor_count: 4" in daily
    assert "부지 검토가 시작됐다. 착공" not in daily  # 3문장 -> 2문장으로 잘림
    assert "- 울산 AX 관련성: 울산 정책 참고사례: " in daily  # 라벨 보정
    assert "고도화 지원 대상이 됐다. 지원은" in daily  # 줄바꿈 정리
    assert "| 2026-10-12 | 4 |" in (published.repo / "index.md").read_text(encoding="utf-8")
    assert "2 files, 5 anchors" in (published.repo / "README.md").read_text(encoding="utf-8")


def test_commit_message_lists_ids_and_roundtrips_to_weekly(published):
    first, *rest = published.msg.splitlines()
    assert first == "auto-publish 2026-10-17: 4 anchors"
    ids, quality = notify.parse_publish_log(published.msg)
    assert sorted(ids) == ["a0000001", "a0000005", "a0000007", "a0000008"]
    assert quality == {"a0000005": "TOO_MANY_SENTENCES:summary", "a0000008": "RELEVANCE_LABEL:relevance"}


def test_second_run_no_new_means_no_commit(published, capsys):
    before = {f.name: f.read_text(encoding="utf-8") for f in (published.repo / "daily").glob("*.md")}
    msg_path = published.tmp / "commit2.txt"
    client = FakeClient()
    rc = auto_publish.main(["--source", str(published.source), "--repo-root", str(published.repo),
                            "--today", "2026-10-18", "--write", "--commit-message", str(msg_path)], client=client)
    out = capsys.readouterr().out
    assert rc == 0 and not msg_path.exists()
    assert before == {f.name: f.read_text(encoding="utf-8") for f in (published.repo / "daily").glob("*.md")}
    assert set(client.calls) == {"a0000002", "a0000003", "a0000004", "a0000006", "a0000009"}  # 보류분만 재시도
    assert_no_leak(out)


def test_hold_issue_dedupes_already_reported(published):
    assert notify.hold_issue(published.report, {h["id"] for h in published.report["held"]}) is None
    title, body = notify.hold_issue(published.report, {"a0000002"})
    assert "a0000002" not in body and "a0000003" in body and "보류 4건" in title


def test_weekly_issue_body_only_ids_and_codes():
    from datetime import datetime
    title, body = notify.weekly_issue(datetime(2026, 10, 12), datetime(2026, 10, 19), ["a0000001"],
                                      {"a0000001": "TOO_LONG:summary"}, {"a0000002": "COPY_RUN:summary"}, 7, 1)
    assert "공개: 1건" in body and "보류: 1건" in body and "실행 실패: 1회" in body
    assert_no_leak(title + body)


def test_exception_prints_type_only(tmp_path, capsys, monkeypatch):
    secret = CASES["a0000001"][1]

    def boom(*a, **k):
        raise ValueError(secret)

    monkeypatch.setattr(auto_publish, "run", boom)
    rc = auto_publish.main(["--source", str(tmp_path)], client=FakeClient())
    out = capsys.readouterr()
    assert rc == 1 and "ERROR ValueError" in out.out
    assert secret not in out.out + out.err


def test_missing_source_does_not_print_path(tmp_path, capsys):
    missing = tmp_path / "숨겨야할경로"
    rc = auto_publish.main(["--source", str(missing)], client=FakeClient())
    out = capsys.readouterr()
    assert rc == 2 and "SOURCE_MISSING" in out.out and "숨겨야할경로" not in out.out + out.err


def test_copy_run_threshold_is_50():
    body = "가나다라마바사아자차" * 10
    assert not [c for c, _, _ in safety.text_issues(body[:49] + ".", "관련.", body) if c == "COPY_RUN"]
    assert [c for c, _, _ in safety.text_issues(body[:50] + ".", "관련.", body) if c == "COPY_RUN"]


def test_truncate_sentences():
    assert safety.truncate_sentences("하나다. 둘이다. 셋이다.", 2, 200) == "하나다. 둘이다."
    assert safety.truncate_sentences("가" * 201 + ".", 2, 200) is None
    assert safety.truncate_sentences("가" * 150 + ". " + "나" * 80 + ".", 2, 200) == "가" * 150 + "."


def _anchor(aid, date=DATE):
    return {"anchor_id": aid, "date": date, "title": f"제목 {aid}", "source": "테스트일보",
            "url": f"https://example.com/{aid}", "grade": "A", "section": "기업·현장", "industries": ["조선"],
            "tags": ["울산", "조선"], "summary": "요약.", "ulsan_relevance": "울산 직접 관련: 이유.",
            "private_path": f"ax-vault-full/AX뉴스/2026/{date}/기사_{aid}.md"}


def test_remove_block_renumbers_and_recounts():
    a, b, c = _anchor("c0000001"), _anchor("c0000002"), _anchor("c0000003")
    full = exporter.render_daily(DATE, [a, b, c])
    assert unpublish_anchor.remove_block(full, "c0000002") == (exporter.render_daily(DATE, [a, c]), True)
    assert unpublish_anchor.remove_block(full, "c0000003") == (exporter.render_daily(DATE, [a, b]), True)
    assert unpublish_anchor.remove_block(exporter.render_daily(DATE, [a]), "c0000001") == (None, True)
    assert unpublish_anchor.remove_block(full, "ffffffff") == (full, False)


def test_unpublish_writes_index_readme_exclude(tmp_path, capsys):
    repo = make_repo(tmp_path)
    (repo / "daily" / f"{DATE}.md").write_text(
        exporter.render_daily(DATE, [_anchor("c0000001"), _anchor("c0000002")]), encoding="utf-8", newline="\n")
    assert unpublish_anchor.unpublish("c0000001", repo, write=True, today="2026-10-17") == 0
    daily = (repo / "daily" / f"{DATE}.md").read_text(encoding="utf-8")
    assert "c0000001" not in daily and "### 1. 제목 c0000002" in daily and "anchor_count: 1" in daily
    assert "| 2026-10-12 | 1 |" in (repo / "index.md").read_text(encoding="utf-8")
    assert "2 files, 2 anchors" in (repo / "README.md").read_text(encoding="utf-8")
    exclude = (repo / "config" / "auto_publish_exclude.txt").read_text(encoding="utf-8")
    assert "c0000001  # unpublished 2026-10-17" in exclude
    assert unpublish_anchor.unpublish("c0000002", repo, write=True) == 0  # 마지막 블록 -> 파일 삭제
    assert not (repo / "daily" / f"{DATE}.md").exists()
    assert "제목 c0000001" not in capsys.readouterr().out
