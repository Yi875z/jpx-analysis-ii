"""レポート生成のモデル設定と、安全分類器に拒否されたときの書き直し（agents/report_agent.py）。

Claude API は呼ばない。client.messages.stream を偽物に差し替えて、どのモデルに何を送ったかを見る。
守りたいこと:
  - effort を必ず明示する（Opus 5.5 の既定は medium で、Opus 5 の high より1段浅い）
  - stop_reason == "refusal" なら REFUSAL_FALLBACK_MODEL で1回だけ書き直す
  - それでも拒否なら例外にする（空のレポートを公開前チェックとメールへ流さない）
"""

from types import SimpleNamespace

import pytest

from agents import report_agent


class _FakeStream:
    def __init__(self, message):
        self._message = message

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get_final_message(self):
        return self._message


class _FakeClient:
    def __init__(self, stop_reasons):
        self.calls = []
        self._stop_reasons = list(stop_reasons)
        self.messages = SimpleNamespace(stream=self._stream)

    def _stream(self, **kw):
        self.calls.append(kw)
        stop = self._stop_reasons.pop(0)
        return _FakeStream(SimpleNamespace(
            stop_reason=stop, model=kw["model"], stop_details=SimpleNamespace(category="bio", explanation="x"),
            content=[SimpleNamespace(type="text", text="本文")]))


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv("CLAUDE_MODEL", raising=False)
    monkeypatch.delenv("CLAUDE_EFFORT", raising=False)


def test_defaults_are_opus_55_with_explicit_effort():
    assert report_agent._get_model() == "claude-opus-5-5"
    assert report_agent._get_effort() == report_agent.DEFAULT_EFFORT
    assert report_agent.DEFAULT_EFFORT in ("low", "medium", "high", "xhigh", "max")


def test_effort_is_sent_and_thinking_is_adaptive():
    client = _FakeClient(["end_turn"])
    msg = report_agent._stream_report(client, "claude-opus-5-5", [], "prompt", "週次レポート")
    assert msg.model == "claude-opus-5-5"
    (kw,) = client.calls
    assert kw["output_config"] == {"effort": report_agent.DEFAULT_EFFORT}
    assert kw["thinking"] == {"type": "adaptive"}   # Opus 5.5 は disabled / budget_tokens が400


def test_refusal_is_rewritten_once_on_the_fallback_model():
    client = _FakeClient(["refusal", "end_turn"])
    msg = report_agent._stream_report(client, "claude-opus-5-5", [], "prompt", "週次レポート")
    assert [c["model"] for c in client.calls] == ["claude-opus-5-5", report_agent.REFUSAL_FALLBACK_MODEL]
    assert msg.model == report_agent.REFUSAL_FALLBACK_MODEL


def test_refusal_on_both_models_raises_instead_of_publishing_empty():
    client = _FakeClient(["refusal", "refusal"])
    with pytest.raises(RuntimeError, match="拒否"):
        report_agent._stream_report(client, "claude-opus-5-5", [], "prompt", "週次レポート")


def test_fallback_model_is_not_tried_twice_when_it_is_the_primary():
    client = _FakeClient(["refusal"])
    with pytest.raises(RuntimeError):
        report_agent._stream_report(client, report_agent.REFUSAL_FALLBACK_MODEL, [], "p", "週次レポート")
    assert len(client.calls) == 1
