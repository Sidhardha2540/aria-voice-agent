import json

from agent.metrics import CallMetrics, log_and_persist_metrics


def test_log_and_persist_metrics_writes_without_running_event_loop(tmp_path):
    metrics = CallMetrics()
    metrics.record_turn(250.0, {"llm_ttfb_ms": 80.0})
    output = tmp_path / "metrics.jsonl"

    log_and_persist_metrics(metrics, str(output))

    rows = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 1
    assert rows[0]["session_id"] == metrics.session_id
    assert rows[0]["latency"]["avg_response_ms"] == 250.0
