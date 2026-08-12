"""回归测试：EmailClassifier 三分类 + 加急检测核心逻辑。

覆盖：
- R1 正文/主题关键词命中 → invoice
- R2 HTML 表格关键词命中 → invoice
- 明确无关标记（通知/广告）→ other
- 可疑情况 → uncertain
- 加急检测
"""
import sys
from pathlib import Path

import pytest

# ── 让 skill 包可被导入 ──
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from skill.src.classifier import EmailClassifier  # noqa: E402


def _make_message(
    subject: str = "",
    body_text: str = "",
    body_html: str = "",
) -> "EmailMessage":
    """构造最小 EmailMessage，仅填 classifier 需要的字段。"""
    from skill.src.email_fetcher import EmailMessage
    return EmailMessage(
        uid=1,
        message_id="test-msg-id",
        subject=subject,
        sender="sender@test.com",
        date="2026-08-06",
        body_html=body_html,
        body_text=body_text,
    )


@pytest.fixture
def classifier() -> EmailClassifier:
    """默认配置的 EmailClassifier 实例。"""
    return EmailClassifier({})


# ── R1 正文/主题关键词命中 ──


def test_r1_body_keyword_hit_invoice(classifier):
    """正文含「开票」→ invoice"""
    msg = _make_message(subject="发票开具申请", body_text="请开具发票")
    r = classifier.classify(msg)
    assert r.category == "invoice"
    assert any("R1" in reason for reason in r.reasons)


def test_r1_subject_keyword_hit_invoice(classifier):
    """主题含「发票」、正文无 → invoice"""
    msg = _make_message(subject="发票申请", body_text="您好")
    r = classifier.classify(msg)
    assert r.category == "invoice"


# ── R2 HTML 表格关键词命中 ──


def test_r2_table_keyword_hit_invoice(classifier):
    """HTML 表格 <th> 中含「发票申请」→ invoice"""
    msg = _make_message(
        subject="申请",
        body_text="",
        body_html="<table><tr><th>发票申请</th></tr></table>",
    )
    r = classifier.classify(msg)
    assert r.category == "invoice"
    assert any("R2" in reason for reason in r.reasons)


def test_r2_table_td_keyword_hit_invoice(classifier):
    """HTML 表格 <td> 中含「发票申请」→ invoice"""
    msg = _make_message(
        subject="申请",
        body_text="",
        body_html="<table><tr><td>发票申请汇总表</td></tr></table>",
    )
    r = classifier.classify(msg)
    assert r.category == "invoice"


# ── 明确无关 → other ──


def test_obvious_other_by_subject_marker(classifier):
    """主题含「通知」→ other"""
    msg = _make_message(subject="系统通知", body_text="")
    r = classifier.classify(msg)
    assert r.category == "other"


def test_obvious_other_by_ad_marker(classifier):
    """主题含「广告」→ other"""
    msg = _make_message(subject="推广广告", body_text="")
    r = classifier.classify(msg)
    assert r.category == "other"


# ── 可疑 → uncertain ──


def test_empty_body_uncertain(classifier):
    """空正文无 HTML → uncertain"""
    msg = _make_message(subject="关于合作", body_text="")
    r = classifier.classify(msg)
    assert r.category == "uncertain"


def test_short_body_uncertain(classifier):
    """短正文无关键词 → uncertain"""
    msg = _make_message(subject="咨询", body_text="你好")
    r = classifier.classify(msg)
    assert r.category == "uncertain"


# ── 加急检测 ──


def test_urgent_detection(classifier):
    """正文含「加急」→ is_urgent=True"""
    msg = _make_message(
        subject="发票申请",
        body_text="请尽快处理，加急",
    )
    r = classifier.classify(msg)
    assert r.is_urgent is True
    assert r.category == "invoice"


def test_not_urgent_by_default(classifier):
    """无加急关键词 → is_urgent=False"""
    msg = _make_message(subject="发票申请", body_text="请处理")
    r = classifier.classify(msg)
    assert r.is_urgent is False


# ── R1+R2 均不命中时的正确分派 ──


def test_unrelated_subject_with_meaningful_body_is_uncertain(classifier):
    """非明确无关主题，正文有一定长度但无关键词 → uncertain"""
    msg = _make_message(
        subject="关于课程咨询",
        body_text=(
            "您好，我想咨询一下课程的相关信息，"
            "希望能够尽快得到回复。谢谢！"
        ),
    )
    r = classifier.classify(msg)
    assert r.category == "uncertain"


# ── HTML 正文剥离后纯文本参与加急检测 ──


def test_urgent_in_html_body(classifier):
    """加急关键词出现在 HTML 正文纯文本中 → is_urgent=True"""
    msg = _make_message(
        subject="发票申请",
        body_text="",
        body_html="<p>这笔订单需要<strong>加急</strong>处理</p>",
    )
    r = classifier.classify(msg)
    assert r.is_urgent is True
