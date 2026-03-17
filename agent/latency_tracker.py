"""
Latency tracking for each conversational turn.

We don't have direct hooks for every low-level event (raw VAD frames, client playback),
but Pipecat's UserBotLatencyObserver provides a breakdown with:
- user_turn_duration_ms  (VAD + STT front half)
- stt_time_ms            (Deepgram)
- llm_ttfb_ms            (OpenAI)
- tts_ttfb_ms            (Cartesia)

We derive:
- vad_latency  ~= user_turn_duration_ms - stt_time_ms
- stt_latency  =  stt_time_ms
- llm_ttft     =  llm_ttfb_ms
- tts_ttfb     =  tts_ttfb_ms
- infra        ~= after_stt_ms - (llm_ttft + tts_ttfb)  (everything else after STT)

Per-turn reports are written to data/latency_log.jsonl.
At session end we write a summary entry with p95/p99 per stage.
"""

from __future__ import annotations

import json
import statistics
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List

from loguru import logger

LATENCY_LOG_PATH = Path("data/latency_log.jsonl")


@dataclass
class TurnLatency:
    turn_id: str
    timestamp_iso: str
    stages: Dict[str, Dict]
    aggregate: Dict[str, object]
    deltas_ms: Dict[str, float]


@dataclass
class SessionLatencySummary:
    session_id: str
    turns: List[TurnLatency] = field(default_factory=list)

    def add(self, t: TurnLatency) -> None:
        self.turns.append(t)

    def _series(self, key: str) -> List[float]:
        return [
            float(t.aggregate.get(key, 0.0))
            for t in self.turns
            if key in t.aggregate
        ]

    def _stage_series(self, stage: str) -> List[float]:
        vals: List[float] = []
        for t in self.turns:
            s = t.stages.get(stage)
            if s and "latency_ms" in s:
                vals.append(float(s["latency_ms"]))
        return vals

    def _percentile(self, xs: List[float], p: float) -> float:
        if not xs:
            return 0.0
        xs = sorted(xs)
        idx = int(round((p / 100.0) * (len(xs) - 1)))
        return xs[idx]

    def build_summary(self) -> Dict[str, object]:
        total_turns = len(self.turns)
        stages = ["vad", "stt", "llm_ttft", "tts_ttfb", "infra"]
        per_stage: Dict[str, Dict[str, float]] = {}
        for s in stages:
            vals = self._stage_series(s)
            if not vals:
                continue
            per_stage[s] = {
                "min": min(vals),
                "max": max(vals),
                "mean": statistics.mean(vals),
                "median": statistics.median(vals),
                "p95": self._percentile(vals, 95),
                "p99": self._percentile(vals, 99),
            }

        v2v = self._series("voice_to_voice_ms")
        bad_turns = [
            t.turn_id
            for t in self.turns
            if any(stage.get("status") == "bad" for stage in t.stages.values())
        ]

        bottlenecks: Dict[str, int] = {}
        for t in self.turns:
            b = t.aggregate.get("bottleneck")
            if b:
                bottlenecks[b] = bottlenecks.get(b, 0) + 1
        most_freq_bottleneck = max(bottlenecks, key=bottlenecks.get) if bottlenecks else None

        def _agg(vals: List[float]) -> Dict[str, float]:
            if not vals:
                return {"min": 0, "max": 0, "mean": 0, "median": 0, "p95": 0, "p99": 0}
            return {
                "min": min(vals),
                "max": max(vals),
                "mean": statistics.mean(vals),
                "median": statistics.median(vals),
                "p95": self._percentile(vals, 95),
                "p99": self._percentile(vals, 99),
            }

        return {
            "session_id": self.session_id,
            "total_turns": total_turns,
            "per_stage": per_stage,
            "voice_to_voice": _agg(v2v),
            "most_frequent_bottleneck": most_freq_bottleneck,
            "bad_turn_ids": bad_turns,
        }


class LatencyTracker:
    def __init__(self, session_id: str | None = None) -> None:
        self.session_id = session_id or str(uuid.uuid4())
        self.session = SessionLatencySummary(session_id=self.session_id)

    # ---- classification helpers ----

    def _status(self, stage: str, ms: float) -> str:
        if stage == "vad":
            if ms < 150:
                return "warning"  # too aggressive
            if ms <= 300:
                return "good"
            if ms <= 500:
                return "warning"
            return "bad"
        if stage == "stt":
            if ms <= 200:
                return "good"
            if ms <= 400:
                return "warning"
            return "bad"
        if stage == "llm_ttft":
            if ms <= 300:
                return "good"
            if ms <= 600:
                return "warning"
            return "bad"
        if stage == "tts_ttfb":
            if ms <= 150:
                return "good"
            if ms <= 300:
                return "warning"
            return "bad"
        if stage == "infra":
            if ms <= 80:
                return "good"
            if ms <= 150:
                return "warning"
            return "bad"
        if stage == "voice_to_voice_ms":
            if ms < 500:
                return "good"
            if ms <= 800:
                return "warning"
            return "bad"
        if stage == "total_turn_ms":
            if ms < 700:
                return "good"
            if ms <= 1100:
                return "warning"
            return "bad"
        return "unknown"

    # ---- main API ----

    def record_turn_from_breakdown(
        self,
        after_stt_ms: float,
        breakdown: Dict[str, float],
    ) -> TurnLatency:
        """
        Build a per-turn report from after-STT latency + parsed breakdown dict.
        """
        user_turn_ms = float(breakdown.get("user_turn_duration_ms", 0.0))
        stt_ms = float(breakdown.get("stt_time_ms", 0.0))
        llm_ms = float(breakdown.get("llm_ttfb_ms", 0.0))
        tts_ms = float(breakdown.get("tts_ttfb_ms", 0.0))

        vad_ms = max(0.0, user_turn_ms - stt_ms) if user_turn_ms and stt_ms else 0.0
        infra_ms = max(0.0, after_stt_ms - (llm_ms + tts_ms)) if after_stt_ms else 0.0

        deltas = {
            "vad": vad_ms,
            "stt": stt_ms,
            "llm_ttft": llm_ms,
            "tts_ttfb": tts_ms,
            "infra": infra_ms,
        }

        stages: Dict[str, Dict[str, object]] = {}
        for name, ms in deltas.items():
            if ms <= 0:
                continue
            stages[name] = {
                "latency_ms": ms,
                "status": self._status(name, ms),
            }

        voice_to_voice_ms = after_stt_ms
        total_turn_ms = user_turn_ms + after_stt_ms

        # Bottleneck = stage with max latency
        bottleneck = None
        if stages:
            bottleneck = max(stages.items(), key=lambda x: x[1]["latency_ms"])[0]

        aggregate = {
            "voice_to_voice_ms": voice_to_voice_ms,
            "voice_to_voice_status": self._status("voice_to_voice_ms", voice_to_voice_ms),
            "total_turn_ms": total_turn_ms,
            "total_turn_status": self._status("total_turn_ms", total_turn_ms),
            "bottleneck": bottleneck,
        }

        turn = TurnLatency(
            turn_id=str(uuid.uuid4()),
            timestamp_iso=datetime.utcnow().isoformat(),
            stages=stages,
            aggregate=aggregate,
            deltas_ms=deltas,
        )
        self._persist_turn(turn)
        self.session.add(turn)
        self._print_console(turn)
        return turn

    def _persist_turn(self, turn: TurnLatency) -> None:
        LATENCY_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with LATENCY_LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(
                json.dumps(
                    {
                        "type": "turn",
                        "session_id": self.session_id,
                        "turn_id": turn.turn_id,
                        "timestamp": turn.timestamp_iso,
                        "stages": turn.stages,
                        "aggregate": turn.aggregate,
                        "deltas_ms": turn.deltas_ms,
                    }
                )
                + "\n"
            )

    def _print_console(self, turn: TurnLatency) -> None:
        s = turn.stages
        agg = turn.aggregate

        def fmt_line(label: str, key: str) -> str | None:
            st = s.get(key)
            if not st:
                return None
            ms = st["latency_ms"]
            status = st["status"]
            emoji = "✅" if status == "good" else "⚠️" if status == "warning" else "❌"
            return f"║  {label:<18}: {ms:4.0f}ms  {emoji} {status:<7}                    ║"

        lines = [
            "╔" + "═" * 58 + "╗",
            f"║  TURN LATENCY BREAKDOWN ({turn.turn_id[:8]})".ljust(59) + "║",
            "╠" + "═" * 58 + "╣",
        ]
        for label, key in [
            ("VAD Endpointing", "vad"),
            ("STT (final)", "stt"),
            ("LLM TTFT", "llm_ttft"),
            ("TTS TTFB", "tts_ttfb"),
            ("Infra overhead", "infra"),
        ]:
            ln = fmt_line(label, key)
            if ln:
                lines.append(ln)

        lines.append("╠" + "═" * 58 + "╣")
        v2v = float(agg.get("voice_to_voice_ms", 0.0))
        v2v_status = agg.get("voice_to_voice_status", "unknown")
        v2v_emoji = "✅" if v2v_status == "good" else "⚠️" if v2v_status == "warning" else "❌"
        lines.append(
            f"║  VOICE-TO-VOICE     : {v2v:4.0f}ms  {v2v_emoji} {v2v_status:<7}                    ║"
        )
        bottleneck = agg.get("bottleneck") or "n/a"
        lines.append(
            f"║  BOTTLENECK         : {str(bottleneck):<25}                     ║"
        )
        lines.append("╚" + "═" * 58 + "╝")

        for ln in lines:
            logger.info(ln)

    def summarize_and_persist(self) -> Dict[str, object]:
        summary = self.session.build_summary()
        LATENCY_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with LATENCY_LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(
                json.dumps(
                    {
                        "type": "session_summary",
                        "session_id": self.session_id,
                        "timestamp": datetime.utcnow().isoformat(),
                        "summary": summary,
                    }
                )
                + "\n"
            )
        logger.info("[LATENCY_SESSION_SUMMARY] {}", json.dumps(summary))
        return summary

