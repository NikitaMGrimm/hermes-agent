"""Regression for #49225 — codex app-server turns must reach the session DB
exactly once.

The codex app-server runtime (``run_codex_app_server_turn``) is an early-return
path that bypasses ``conversation_loop`` and therefore never runs the loop's
per-step ``_persist_session()`` flushes. Before the fix, the projected
assistant/tool messages were persisted *nowhere* (state.db got only
session_meta rows), leaving ``session_search`` (FTS) and conversation-distill
blind to real gateway conversations.

The fix has the codex runtime flush its own projected messages via
``_flush_messages_to_session_db()`` (idempotent through the intrinsic
``_DB_PERSISTED_MARKER``) and return ``agent_persisted=True`` so the gateway
skips its own ``append_to_transcript`` DB write. This is critical: the inbound
user turn is already flushed at turn start (``turn_context._persist_session``),
and ``append_message`` is a raw INSERT with no dedup — a gateway re-write would
duplicate the user turn (#860 / #42039). This test locks in:

1. ``run_codex_app_server_turn`` flushes projected messages and returns
   ``agent_persisted=True``.
2. Exactly-once persistence: the already-flushed user turn is NOT re-written,
   and the new projected assistant message lands once.
3. The gateway resolution expression preserves standard-runtime behaviour.
"""

import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from agent.codex_runtime import run_codex_app_server_turn
from hermes_state import SessionDB
from run_agent import AIAgent


def _make_turn():
    return SimpleNamespace(
        interrupted=False,
        error=None,
        thread_id="thread-1",
        turn_id="turn-1",
        projected_messages=[{"role": "assistant", "content": "CODEX_ASSISTANT"}],
        tool_iterations=0,
        final_text="CODEX_ASSISTANT",
        should_retire=False,
    )


def _make_agent(session_db=None, session_id="sess-codex"):
    agent = MagicMock()
    # Pre-seed the session so run_codex_app_server_turn skips the spawn block.
    agent._codex_session = MagicMock()
    agent._codex_session.run_turn.return_value = _make_turn()
    agent._codex_session_runtime_key = (None, None)
    agent.requested_provider = ""
    agent.provider = ""
    agent.model = None
    agent.tool_progress_callback = None
    agent._iters_since_skill = 0
    agent._skill_nudge_interval = 0
    agent.valid_tool_names = set()
    agent._session_db = session_db
    agent._session_db_created = True
    agent.session_id = session_id
    agent._interrupt_requested = False
    agent._interrupt_message = None
    return agent


def test_codex_success_flushes_and_reports_persisted():
    """Codex success turn must self-persist and return agent_persisted=True."""
    agent = _make_agent(session_db=None)  # no DB -> flush is a no-op, still True
    result = run_codex_app_server_turn(
        agent,
        user_message="hello",
        original_user_message="hello",
        messages=[{"role": "user", "content": "hello"}],
        effective_task_id="task-1",
    )
    assert result["completed"] is True
    assert isinstance(result["messages"][-1]["timestamp"], float)
    # With the agent as sole persister, the gateway must SKIP its DB write.
    assert result["agent_persisted"] is True


def test_codex_user_interrupt_is_reported_and_cleared():
    agent = _make_agent(session_db=None)
    turn = _make_turn()
    turn.interrupted = True
    turn.final_text = ""

    def interrupted_turn(*, user_input):
        agent._interrupt_requested = True
        agent._interrupt_message = "new correction"
        return turn

    agent._codex_session.run_turn.side_effect = interrupted_turn

    def clear_interrupt():
        agent._interrupt_requested = False
        agent._interrupt_message = None

    agent.clear_interrupt.side_effect = clear_interrupt
    result = run_codex_app_server_turn(
        agent,
        user_message="hello",
        original_user_message="hello",
        messages=[{"role": "user", "content": "hello"}],
        effective_task_id="task-1",
    )

    assert result["interrupted"] is True
    assert result["interrupt_message"] == "new correction"
    agent.clear_interrupt.assert_called_once_with()
    assert agent._interrupt_requested is False


def test_codex_late_interrupt_reconciles_completed_session_result():
    """A stop racing turn/completed belongs to this turn, never the next one."""
    agent = _make_agent(session_db=None)
    turn = _make_turn()

    def completed_while_interrupting(*, user_input):
        agent._interrupt_requested = True
        agent._interrupt_message = "stop at completion"
        return turn

    agent._codex_session.run_turn.side_effect = completed_while_interrupting

    def clear_interrupt():
        agent._interrupt_requested = False
        agent._interrupt_message = None

    agent.clear_interrupt.side_effect = clear_interrupt
    result = run_codex_app_server_turn(
        agent,
        user_message="hello",
        original_user_message="hello",
        messages=[{"role": "user", "content": "hello"}],
        effective_task_id="task-1",
    )

    assert result["completed"] is False
    assert result["partial"] is True
    assert result["interrupted"] is True
    assert result["interrupt_message"] == "stop at completion"
    assert agent._interrupt_requested is False


def test_codex_interrupt_preserved_after_compaction_skips_next_turn():
    """A stop consumed by native compaction must still abort the logical turn."""
    from agent.conversation_compression import (
        _compress_context_via_codex_app_server,
    )

    agent = _make_agent(session_db=None)
    agent._cached_system_prompt = "system"

    def interrupted_compaction():
        agent._interrupt_requested = True
        agent._interrupt_message = "stop during compaction"
        return SimpleNamespace(interrupted=True, error=None, should_retire=False)

    agent._codex_session.compact_thread.side_effect = interrupted_compaction

    def clear_interrupt():
        agent._interrupt_requested = False
        agent._interrupt_message = None

    agent.clear_interrupt.side_effect = clear_interrupt
    messages = [{"role": "user", "content": "hello"}]

    heartbeat = MagicMock()
    heartbeat.start.return_value = heartbeat
    with patch(
        "agent.conversation_compression._CompressionActivityHeartbeat",
        return_value=heartbeat,
    ):
        compressed, system_prompt = _compress_context_via_codex_app_server(
            agent,
            messages,
            "system",
            approx_tokens=100_000,
            force=True,
        )

    assert compressed is messages
    assert system_prompt == "system"
    assert agent._interrupt_requested is True

    result = run_codex_app_server_turn(
        agent,
        user_message="hello",
        original_user_message="hello",
        messages=messages,
        effective_task_id="task-1",
    )

    agent._codex_session.run_turn.assert_not_called()
    # Draining is idempotent; the contract is that the private wakeup is
    # consumed before the logical turn returns, not a particular call count.
    assert agent._codex_session.consume_interrupt_request.call_count >= 1
    assert result["completed"] is False
    assert result["partial"] is True
    assert result["interrupted"] is True
    assert result["interrupt_message"] == "stop during compaction"
    agent.clear_interrupt.assert_called_once_with()


def test_codex_turn_persists_each_message_exactly_once():
    """The user turn (flushed at turn start) must not be duplicated; the
    projected assistant message must land once.  Uses a real SessionDB and the
    real AIAgent._flush_messages_to_session_db to prove no #860/#42039
    duplicate-write regression on the codex path."""
    tmp = tempfile.mkdtemp(prefix="codex_persist_")
    try:
        db = SessionDB(Path(tmp) / "state.db")
        sid = "sess-codex-once"
        db.create_session(session_id=sid, source="telegram", model="codex")

        # Real agent bound to this DB/session, minimal construction.
        agent = AIAgent(
            api_key="test-key",
            base_url="https://openrouter.ai/api/v1",
            quiet_mode=True,
            skip_context_files=True,
            skip_memory=True,
            session_db=db,
            session_id=sid,
        )
        agent._session_db_created = True
        agent._codex_session = MagicMock()
        agent._codex_session.run_turn.return_value = _make_turn()
        setattr(agent, "_codex_session_runtime_key", (None, None))
        agent.tool_progress_callback = None

        # Model the real flow: the inbound user turn is flushed at turn start
        # (turn_context._persist_session) on the SAME `messages` list the codex
        # path later reuses. That flush stamps _DB_PERSISTED_MARKER on the user
        # dict, so the codex-path flush skips it — no duplicate.
        user_msg = {"role": "user", "content": "USER_TURN"}
        messages = [user_msg]
        agent._flush_messages_to_session_db(messages)  # turn-start flush

        result = run_codex_app_server_turn(
            agent,
            user_message="USER_TURN",
            original_user_message="USER_TURN",
            messages=messages,
            effective_task_id="task-1",
        )
        assert result["agent_persisted"] is True

        rows = db.get_messages(sid, include_inactive=True)
        contents = [r["content"] for r in rows]
        # Exactly one user turn, exactly one assistant turn — no duplicates.
        assert contents.count("USER_TURN") == 1, contents
        assert contents.count("CODEX_ASSISTANT") == 1, contents
        assistant_row = next(
            row for row in rows if row["content"] == "CODEX_ASSISTANT"
        )
        assert isinstance(assistant_row["timestamp"], float)
        # session_search can now see the codex conversation.
        hits = {r["session_id"] for r in db.search_messages("CODEX_ASSISTANT")}
        assert sid in hits
    finally:
        import shutil

        shutil.rmtree(tmp)


class TestGatewayPersistedResolution:
    """The gateway default must preserve standard-runtime skip-db behaviour."""

    @staticmethod
    def _resolve_persistence_block(agent_result, session_db_present):
        # gateway/run.py persistence block:
        #   agent_persisted = agent_result.get("agent_persisted", self._session_db is not None)
        return agent_result.get("agent_persisted", session_db_present)

    @staticmethod
    def _resolve_passthrough(result_holder0):
        # gateway/run.py result_holder passthrough:
        #   result_holder[0].get("agent_persisted", True) if result_holder[0] else True
        return result_holder0.get("agent_persisted", True) if result_holder0 else True

    def test_codex_result_keeps_gateway_skip(self):
        # Codex now self-persists → gateway must SKIP (agent_persisted True).
        codex = {"agent_persisted": True}
        assert self._resolve_persistence_block(codex, True) is True
        assert self._resolve_persistence_block(codex, False) is True
        assert self._resolve_passthrough(codex) is True

    def test_standard_runtime_preserves_skip_db(self):
        # Standard runtime omits the key → old behaviour: skip iff DB present.
        standard = {"final_response": "ok"}
        assert self._resolve_persistence_block(standard, True) is True
        assert self._resolve_persistence_block(standard, False) is False
        assert self._resolve_passthrough(standard) is True

    def test_missing_result_holder_defaults_persisted(self):
        assert self._resolve_passthrough(None) is True
