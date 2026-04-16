from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from uuid import uuid4
from unittest.mock import MagicMock, patch

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.models import (
    BacktestRun,
    ExecutionStrategyState,
    LiveSignal,
    LiveTask,
    PortfolioBook,
    PortfolioFill,
    RunTrace,
    Skill,
    StrategyState,
    TraceExecutionDetail,
)
from app.runtime.market_sync_loop import MarketSyncLoopManager, MarketSyncLoopSnapshot
from app.services.agent_runner_client import AgentRunnerErrorDetail, AgentRunnerRequestError
from app.services.agent_run_recovery import AgentRunRecoveryError
from app.services.backtest_service import BacktestService, execute_backtest_job
from app.services.execution_cleanup import delete_strategy_cascade
from app.services.execution_lifecycle import (
    BACKTEST_STATUS_COMPLETED,
    BACKTEST_STATUS_FAILED,
    BACKTEST_STATUS_PAUSED,
    BACKTEST_STATUS_RUNNING,
    BACKTEST_STATUS_STOPPED,
    LIVE_STATUS_ACTIVE,
    LIVE_STATUS_PAUSED,
    LIVE_STATUS_STOPPED,
)
from app.services.live_service import (
    LiveTaskConflictError,
    LiveTaskOwnershipError,
    LiveTaskService,
    LiveTaskTriggerRejectedError,
    dispatch_sync_driven_live_tasks,
    execute_live_task,
    trigger_live_task_manually,
)
from app.services.market_data_sync import MarketSyncSweepResult
from app.services.portfolio_engine import BACKTEST_SCOPE_KIND, LIVE_SCOPE_KIND
from app.services.serializers import trace_to_dict


class ExecutionLifecycleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
            future=True,
        )
        self.session_factory = sessionmaker(bind=self.engine, autoflush=False, autocommit=False, future=True)
        Base.metadata.create_all(self.engine)

    def tearDown(self) -> None:
        Base.metadata.drop_all(self.engine)
        self.engine.dispose()

    def create_skill(self, *, title: str = "Momentum Skill", cadence: str = "15m") -> Skill:
        with self.session_factory() as db:
            skill = Skill(
                id=self.make_id("skill"),
                title=title,
                raw_text=f"# {title}\n\nRun every {cadence}.",
                source_hash=f"sha256:{uuid4().hex}",
                validation_status="passed",
                envelope_json={"trigger": {"value": cadence}},
                validation_errors_json=[],
                validation_warnings_json=[],
            )
            db.add(skill)
            db.commit()
            db.refresh(skill)
            return skill

    def make_id(self, prefix: str) -> str:
        return f"{prefix}-{uuid4().hex[:10]}"

    def count_rows(self, model, *criteria) -> int:
        with self.session_factory() as db:
            query = select(func.count()).select_from(model)
            if criteria:
                query = query.where(*criteria)
            return int(db.scalar(query) or 0)

    def test_backtest_checkpoint_pause_resume_and_delete_cleanup(self) -> None:
        skill = self.create_skill(title="Backtest Skill")
        start_time = datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc)
        end_time = start_time + timedelta(minutes=45)
        trigger_times = [start_time, start_time + timedelta(minutes=15), start_time + timedelta(minutes=30)]
        response_payload = {
            "decision": {"action": "skip"},
            "reasoning_summary": "Wait for confirmation.",
            "tool_calls": [
                {
                    "tool_name": "scan_market",
                    "arguments": {"top_n": 8},
                    "status": "ok",
                    "execution_timing": {
                        "started_at_ms": 1704067200100,
                        "completed_at_ms": 1704067200135,
                        "duration_ms": 35,
                    },
                }
            ],
            "provider": "mock-runner",
            "execution_timing": {
                "started_at_ms": 1704067200000,
                "completed_at_ms": 1704067200091,
                "duration_ms": 91,
            },
            "execution_breakdown": {
                "tool_execution_total_ms": 35,
                "llm_wait_total_ms": 48,
                "other_overhead_ms": 8,
            },
            "llm_rounds": [
                {
                    "round_index": 1,
                    "started_at_ms": 1704067200000,
                    "completed_at_ms": 1704067200040,
                    "llm_round_duration_ms": 40,
                    "tool_call_count": 1,
                    "result_type": "tool_calls",
                },
                {
                    "round_index": 2,
                    "started_at_ms": 1704067200043,
                    "completed_at_ms": 1704067200051,
                    "llm_round_duration_ms": 8,
                    "tool_call_count": 0,
                    "result_type": "final_output",
                },
            ],
        }

        with (
            patch(
                "app.services.backtest_service.get_market_data_coverage",
                return_value=(start_time - timedelta(days=1), end_time + timedelta(days=1)),
            ),
            patch("app.services.backtest_service.build_trigger_times", return_value=(trigger_times, False)),
            patch(
                "app.services.backtest_service.build_market_snapshot_for_backtest",
                return_value={"market_candidates": [{"symbol": "BTC-USDT-SWAP"}], "provider": "mock-provider"},
            ),
            patch("app.services.backtest_service.SessionLocal", self.session_factory),
        ):
            with self.session_factory() as db:
                created = BacktestService(db).create_run(skill.id, start_time, end_time, 10_000.0)
                run_id = created["id"]

            agent_call_count = {"value": 0}

            def pause_after_first_step(_payload):
                agent_call_count["value"] += 1
                if agent_call_count["value"] == 1:
                    with self.session_factory() as other_db:
                        run = other_db.get(BacktestRun, run_id)
                        self.assertIsNotNone(run)
                        run.control_requested = "pause"
                        other_db.add(run)
                        other_db.commit()
                return response_payload

            with patch(
                "app.services.backtest_service.execute_agent_run_with_recovery",
                side_effect=lambda payload, **_kwargs: (
                    pause_after_first_step(payload),
                    {"attempt_count": 1, "recovered": False, "retry_count": 0},
                ),
            ):
                execute_backtest_job(run_id)

            with self.session_factory() as db:
                service = BacktestService(db)
                paused_run = db.get(BacktestRun, run_id)
                self.assertIsNotNone(paused_run)
                self.assertEqual(paused_run.status, BACKTEST_STATUS_PAUSED)
                self.assertEqual(paused_run.completed_trigger_count, 1)
                paused_payload = service.get_run(run_id)
                self.assertEqual(paused_payload["progress"]["completed_steps"], 1)
                self.assertEqual(paused_payload["progress"]["total_steps"], 3)
                self.assertEqual(paused_payload["available_actions"], ["resume", "stop", "delete"])

            with self.session_factory() as db:
                resumed_payload, should_enqueue = BacktestService(db).control_run(run_id, "resume")
                self.assertTrue(should_enqueue)
                self.assertEqual(resumed_payload["status"], BACKTEST_STATUS_RUNNING)

            with patch(
                "app.services.backtest_service.execute_agent_run_with_recovery",
                return_value=(response_payload, {"attempt_count": 1, "recovered": False, "retry_count": 0}),
            ):
                execute_backtest_job(run_id)

            with self.session_factory() as db:
                completed_run = db.get(BacktestRun, run_id)
                self.assertIsNotNone(completed_run)
                self.assertEqual(completed_run.status, BACKTEST_STATUS_COMPLETED)
                self.assertEqual(completed_run.completed_trigger_count, 3)
                self.assertIsNotNone(completed_run.summary_json)
                self.assertEqual(
                    db.scalar(select(func.count()).select_from(RunTrace).where(RunTrace.run_id == run_id)),
                    3,
                )
                stored_trace = db.scalars(
                    select(RunTrace).where(RunTrace.run_id == run_id).order_by(RunTrace.trace_index.asc())
                ).first()
                self.assertIsNotNone(stored_trace)
                assert stored_trace is not None
                self.assertEqual(stored_trace.decision_json["_runtime_metrics"]["execution_timing"]["duration_ms"], 91)
                trace_payload = BacktestService(db).get_traces(run_id)[0]
                self.assertEqual(trace_payload["execution_timing"]["duration_ms"], 91)
                self.assertEqual(trace_payload["execution_breakdown"]["llm_wait_total_ms"], 48)
                self.assertEqual(trace_payload["llm_rounds"][0]["tool_call_count"], 1)
                self.assertEqual(trace_payload["tool_calls"][0]["execution_timing"]["duration_ms"], 35)
                self.assertNotIn("_runtime_metrics", trace_payload["decision"])

            with self.session_factory() as db:
                BacktestService(db).delete_run(run_id)
                db.commit()

        self.assertEqual(self.count_rows(BacktestRun, BacktestRun.id == run_id), 0)
        self.assertEqual(self.count_rows(RunTrace, RunTrace.run_id == run_id), 0)
        self.assertEqual(
            self.count_rows(
                PortfolioBook,
                PortfolioBook.scope_kind == BACKTEST_SCOPE_KIND,
                PortfolioBook.scope_id == run_id,
            ),
            0,
        )
        self.assertEqual(
            self.count_rows(
                ExecutionStrategyState,
                ExecutionStrategyState.scope_kind == BACKTEST_SCOPE_KIND,
                ExecutionStrategyState.scope_id == run_id,
            ),
            0,
        )

    def test_backtest_records_recovery_metadata_when_runner_recovers(self) -> None:
        skill = self.create_skill(title="Recovering Backtest Skill")
        start_time = datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc)
        end_time = start_time + timedelta(minutes=30)
        trigger_times = [start_time, start_time + timedelta(minutes=15)]
        response_payload = {
            "decision": {"action": "skip", "reason": "Wait."},
            "reasoning_summary": "Recovered after retries.",
            "tool_calls": [],
            "provider": "mock-runner",
        }

        with (
            patch(
                "app.services.backtest_service.get_market_data_coverage",
                return_value=(start_time - timedelta(days=1), end_time + timedelta(days=1)),
            ),
            patch("app.services.backtest_service.build_trigger_times", return_value=(trigger_times, False)),
            patch(
                "app.services.backtest_service.build_market_snapshot_for_backtest",
                return_value={"market_candidates": [{"symbol": "BTC-USDT-SWAP"}], "provider": "mock-provider"},
            ),
            patch("app.services.backtest_service.SessionLocal", self.session_factory),
        ):
            with self.session_factory() as db:
                run_id = BacktestService(db).create_run(skill.id, start_time, end_time, 10_000.0)["id"]

            recoveries = [
                {"attempt_count": 3, "recovered": True, "retry_count": 2},
                {"attempt_count": 1, "recovered": False, "retry_count": 0},
            ]

            def fake_recovery(*_args, **_kwargs):
                return response_payload, recoveries.pop(0)

            with patch("app.services.backtest_service.execute_agent_run_with_recovery", side_effect=fake_recovery):
                execute_backtest_job(run_id)

            with self.session_factory() as db:
                run = db.get(BacktestRun, run_id)
                self.assertIsNotNone(run)
                assert run is not None
                self.assertEqual(run.status, BACKTEST_STATUS_COMPLETED)
                self.assertIsNone(run.last_runtime_error_json)
                traces = BacktestService(db).get_traces(run_id)
                self.assertEqual(traces[0]["recovery"]["attempt_count"], 3)
                self.assertTrue(traces[0]["recovery"]["recovered"])
                self.assertEqual(traces[1]["recovery"]["attempt_count"], 1)
                self.assertFalse(traces[1]["recovery"]["recovered"])

    def test_backtest_failed_retry_keeps_checkpoint_and_resume_replays_same_step(self) -> None:
        skill = self.create_skill(title="Retry Resume Backtest Skill")
        start_time = datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc)
        end_time = start_time + timedelta(minutes=45)
        trigger_times = [start_time, start_time + timedelta(minutes=15), start_time + timedelta(minutes=30)]
        response_payload = {
            "decision": {"action": "skip", "reason": "Wait."},
            "reasoning_summary": "Recovered.",
            "tool_calls": [],
            "provider": "mock-runner",
        }
        final_error = AgentRunnerRequestError(
            operation="run execution",
            status_code=503,
            detail=AgentRunnerErrorDetail(
                retryable=True,
                source="agent_runner",
                error_type="too_many_requests",
                message="Too Many Requests",
            ),
        )

        with (
            patch(
                "app.services.backtest_service.get_market_data_coverage",
                return_value=(start_time - timedelta(days=1), end_time + timedelta(days=1)),
            ),
            patch("app.services.backtest_service.build_trigger_times", return_value=(trigger_times, False)),
            patch(
                "app.services.backtest_service.build_market_snapshot_for_backtest",
                return_value={"market_candidates": [{"symbol": "BTC-USDT-SWAP"}], "provider": "mock-provider"},
            ),
            patch("app.services.backtest_service.SessionLocal", self.session_factory),
        ):
            with self.session_factory() as db:
                run_id = BacktestService(db).create_run(skill.id, start_time, end_time, 10_000.0)["id"]

            first_pass = [
                (response_payload, {"attempt_count": 1, "recovered": False, "retry_count": 0}),
                AgentRunRecoveryError(attempt_count=4, final_error=final_error),
            ]

            def first_pass_recovery(*_args, **_kwargs):
                result = first_pass.pop(0)
                if isinstance(result, Exception):
                    raise result
                return result

            with patch("app.services.backtest_service.execute_agent_run_with_recovery", side_effect=first_pass_recovery):
                execute_backtest_job(run_id)

            with self.session_factory() as db:
                failed_run = db.get(BacktestRun, run_id)
                self.assertIsNotNone(failed_run)
                assert failed_run is not None
                self.assertEqual(failed_run.status, BACKTEST_STATUS_FAILED)
                self.assertEqual(failed_run.completed_trigger_count, 1)
                self.assertEqual(failed_run.last_runtime_error_json["failed_trace_index"], 1)
                self.assertEqual(failed_run.last_runtime_error_json["attempt_count"], 4)
                self.assertEqual(self.count_rows(RunTrace, RunTrace.run_id == run_id), 1)

            with self.session_factory() as db:
                resumed_payload, should_enqueue = BacktestService(db).control_run(run_id, "resume")
                self.assertTrue(should_enqueue)
                self.assertEqual(resumed_payload["status"], BACKTEST_STATUS_RUNNING)
                self.assertIsNone(resumed_payload["last_runtime_error"])

            second_pass = [
                (response_payload, {"attempt_count": 2, "recovered": True, "retry_count": 1}),
                (response_payload, {"attempt_count": 1, "recovered": False, "retry_count": 0}),
            ]
            with patch(
                "app.services.backtest_service.execute_agent_run_with_recovery",
                side_effect=lambda *_args, **_kwargs: second_pass.pop(0),
            ):
                execute_backtest_job(run_id)

            with self.session_factory() as db:
                completed_run = db.get(BacktestRun, run_id)
                self.assertIsNotNone(completed_run)
                assert completed_run is not None
                self.assertEqual(completed_run.status, BACKTEST_STATUS_COMPLETED)
                self.assertEqual(completed_run.completed_trigger_count, 3)
                self.assertIsNone(completed_run.last_runtime_error_json)
                traces = db.scalars(
                    select(RunTrace).where(RunTrace.run_id == run_id).order_by(RunTrace.trace_index.asc())
                ).all()
                self.assertEqual([trace.trace_index for trace in traces], [0, 1, 2])

    def test_failed_backtest_resumes_from_last_successful_checkpoint(self) -> None:
        skill = self.create_skill(title="Recoverable Backtest Skill")
        start_time = datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc)
        end_time = start_time + timedelta(minutes=45)
        trigger_times = [start_time, start_time + timedelta(minutes=15), start_time + timedelta(minutes=30)]
        response_payload = {
            "decision": {"action": "skip"},
            "reasoning_summary": "Wait for confirmation.",
            "tool_calls": [],
            "provider": "mock-runner",
        }

        with (
            patch(
                "app.services.backtest_service.get_market_data_coverage",
                return_value=(start_time - timedelta(days=1), end_time + timedelta(days=1)),
            ),
            patch("app.services.backtest_service.build_trigger_times", return_value=(trigger_times, False)),
            patch(
                "app.services.backtest_service.build_market_snapshot_for_backtest",
                return_value={"market_candidates": [{"symbol": "BTC-USDT-SWAP"}], "provider": "mock-provider"},
            ),
            patch("app.services.backtest_service.SessionLocal", self.session_factory),
        ):
            with self.session_factory() as db:
                created = BacktestService(db).create_run(skill.id, start_time, end_time, 10_000.0)
                run_id = created["id"]

            agent_responses = [
                response_payload,
                RuntimeError("runner exploded"),
            ]

            def fail_on_second_step(_payload):
                next_item = agent_responses.pop(0)
                if isinstance(next_item, Exception):
                    raise next_item
                return next_item

            with patch(
                "app.services.backtest_service.execute_agent_run_with_recovery",
                side_effect=lambda payload, **_kwargs: (
                    fail_on_second_step(payload),
                    {"attempt_count": 1, "recovered": False, "retry_count": 0},
                ),
            ):
                execute_backtest_job(run_id)

            with self.session_factory() as db:
                service = BacktestService(db)
                failed_run = db.get(BacktestRun, run_id)
                self.assertIsNotNone(failed_run)
                assert failed_run is not None
                self.assertEqual(failed_run.status, BACKTEST_STATUS_FAILED)
                self.assertEqual(failed_run.completed_trigger_count, 1)
                self.assertIn("Backtest step 2", failed_run.error_message or "")
                failed_payload = service.get_run(run_id)
                self.assertEqual(failed_payload["available_actions"], ["resume", "delete"])
                trace_rows = db.scalars(
                    select(RunTrace).where(RunTrace.run_id == run_id).order_by(RunTrace.trace_index.asc())
                ).all()
                self.assertEqual(len(trace_rows), 1)
                first_trace_id = trace_rows[0].id

            with self.session_factory() as db:
                resumed_payload, should_enqueue = BacktestService(db).control_run(run_id, "resume")
                self.assertTrue(should_enqueue)
                self.assertEqual(resumed_payload["status"], BACKTEST_STATUS_RUNNING)
                self.assertIsNone(resumed_payload["error_message"])

            with patch(
                "app.services.backtest_service.execute_agent_run_with_recovery",
                return_value=(response_payload, {"attempt_count": 1, "recovered": False, "retry_count": 0}),
            ):
                execute_backtest_job(run_id)

            with self.session_factory() as db:
                completed_run = db.get(BacktestRun, run_id)
                self.assertIsNotNone(completed_run)
                assert completed_run is not None
                self.assertEqual(completed_run.status, BACKTEST_STATUS_COMPLETED)
                self.assertEqual(completed_run.completed_trigger_count, 3)
                trace_rows = db.scalars(
                    select(RunTrace).where(RunTrace.run_id == run_id).order_by(RunTrace.trace_index.asc())
                ).all()
                self.assertEqual([trace.trace_index for trace in trace_rows], [0, 1, 2])
                self.assertEqual(trace_rows[0].id, first_trace_id)
                self.assertIsNotNone(completed_run.summary_json)

    def test_failed_backtest_can_resume_finalization_without_rerunning_triggers(self) -> None:
        skill = self.create_skill(title="Finalization Resume Skill")
        start_time = datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc)
        end_time = start_time + timedelta(minutes=45)
        trigger_times = [start_time, start_time + timedelta(minutes=15), start_time + timedelta(minutes=30)]
        response_payload = {
            "decision": {"action": "skip"},
            "reasoning_summary": "Stay flat.",
            "tool_calls": [],
            "provider": "mock-runner",
        }

        with (
            patch(
                "app.services.backtest_service.get_market_data_coverage",
                return_value=(start_time - timedelta(days=1), end_time + timedelta(days=1)),
            ),
            patch("app.services.backtest_service.build_trigger_times", return_value=(trigger_times, False)),
            patch(
                "app.services.backtest_service.build_market_snapshot_for_backtest",
                return_value={"market_candidates": [{"symbol": "BTC-USDT-SWAP"}], "provider": "mock-provider"},
            ),
            patch("app.services.backtest_service.SessionLocal", self.session_factory),
        ):
            with self.session_factory() as db:
                created = BacktestService(db).create_run(skill.id, start_time, end_time, 10_000.0)
                run_id = created["id"]

            with (
                patch(
                    "app.services.backtest_service.execute_agent_run_with_recovery",
                    return_value=(response_payload, {"attempt_count": 1, "recovered": False, "retry_count": 0}),
                ),
                patch(
                    "app.services.backtest_service.compute_max_drawdown",
                    side_effect=[RuntimeError("summary aggregation failed"), 0.0],
                ),
            ):
                execute_backtest_job(run_id)

            with self.session_factory() as db:
                service = BacktestService(db)
                failed_run = db.get(BacktestRun, run_id)
                self.assertIsNotNone(failed_run)
                assert failed_run is not None
                self.assertEqual(failed_run.status, BACKTEST_STATUS_FAILED)
                self.assertEqual(failed_run.completed_trigger_count, 3)
                self.assertEqual(failed_run.total_trigger_count, 3)
                self.assertIsNone(failed_run.summary_json)
                failed_payload = service.get_run(run_id)
                self.assertEqual(failed_payload["progress"]["completed_steps"], 3)
                self.assertEqual(failed_payload["progress"]["total_steps"], 3)
                self.assertEqual(failed_payload["available_actions"], ["resume", "delete"])

            with self.session_factory() as db:
                resumed_payload, should_enqueue = BacktestService(db).control_run(run_id, "resume")
                self.assertTrue(should_enqueue)
                self.assertEqual(resumed_payload["status"], BACKTEST_STATUS_RUNNING)

            with patch(
                "app.services.backtest_service.execute_agent_run_with_recovery",
                side_effect=AssertionError("resume should not rerun completed trigger steps"),
            ):
                execute_backtest_job(run_id)

            with self.session_factory() as db:
                completed_run = db.get(BacktestRun, run_id)
                self.assertIsNotNone(completed_run)
                assert completed_run is not None
                self.assertEqual(completed_run.status, BACKTEST_STATUS_COMPLETED)
                self.assertEqual(completed_run.completed_trigger_count, 3)
                self.assertIsNotNone(completed_run.summary_json)
                self.assertEqual(
                    db.scalar(select(func.count()).select_from(RunTrace).where(RunTrace.run_id == run_id)),
                    3,
                )

    def test_stopped_and_completed_backtests_cannot_resume(self) -> None:
        skill = self.create_skill(title="Non-resumable Backtest Skill")
        start_time = datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc)
        end_time = start_time + timedelta(minutes=30)
        trigger_times = [start_time, start_time + timedelta(minutes=15)]

        with (
            patch(
                "app.services.backtest_service.get_market_data_coverage",
                return_value=(start_time - timedelta(days=1), end_time + timedelta(days=1)),
            ),
            patch("app.services.backtest_service.build_trigger_times", return_value=(trigger_times, False)),
        ):
            with self.session_factory() as db:
                stopped_run = BacktestService(db).create_run(skill.id, start_time, end_time, 10_000.0)
                completed_run = BacktestService(db).create_run(skill.id, start_time, end_time, 10_000.0)
                stopped_id = stopped_run["id"]
                completed_id = completed_run["id"]

            with self.session_factory() as db:
                stopped = db.get(BacktestRun, stopped_id)
                completed = db.get(BacktestRun, completed_id)
                self.assertIsNotNone(stopped)
                self.assertIsNotNone(completed)
                assert stopped is not None
                assert completed is not None
                stopped.status = BACKTEST_STATUS_STOPPED
                completed.status = BACKTEST_STATUS_COMPLETED
                completed.total_trigger_count = 2
                completed.completed_trigger_count = 2
                db.add(stopped)
                db.add(completed)
                db.commit()

            with self.session_factory() as db:
                service = BacktestService(db)
                with self.assertRaises(ValueError):
                    service.control_run(stopped_id, "resume")
                with self.assertRaises(ValueError):
                    service.control_run(completed_id, "resume")

    def test_backtest_rolls_back_state_patch_when_execution_fails_after_agent_response(self) -> None:
        skill = self.create_skill(title="Backtest State Rollback")
        start_time = datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc)
        end_time = start_time + timedelta(minutes=30)
        trigger_times = [start_time, start_time + timedelta(minutes=15)]
        response_payload = {
            "decision": {
                "action": "skip",
                "reason": "Record staged state only after a successful cycle.",
                "state_patch": {"focus_symbol": "BTC-USDT-SWAP", "last_action": "watch"},
            },
            "reasoning_summary": "Prepared a state update before execution.",
            "tool_calls": [],
            "provider": "mock-runner",
        }

        with (
            patch(
                "app.services.backtest_service.get_market_data_coverage",
                return_value=(start_time - timedelta(days=1), end_time + timedelta(days=1)),
            ),
            patch("app.services.backtest_service.build_trigger_times", return_value=(trigger_times, False)),
            patch(
                "app.services.backtest_service.build_market_snapshot_for_backtest",
                return_value={"market_candidates": [{"symbol": "BTC-USDT-SWAP"}], "provider": "mock-provider"},
            ),
            patch("app.services.backtest_service.SessionLocal", self.session_factory),
        ):
            with self.session_factory() as db:
                run_id = BacktestService(db).create_run(skill.id, start_time, end_time, 10_000.0)["id"]

            with (
                patch(
                    "app.services.backtest_service.execute_agent_run_with_recovery",
                    return_value=(response_payload, {"attempt_count": 1, "recovered": False, "retry_count": 0}),
                ),
                patch(
                    "app.services.backtest_service.PortfolioEngine.apply_decision",
                    side_effect=RuntimeError("synthetic apply failure"),
                ),
            ):
                execute_backtest_job(run_id)

        with self.session_factory() as db:
            run = db.get(BacktestRun, run_id)
            self.assertIsNotNone(run)
            assert run is not None
            self.assertEqual(run.status, BACKTEST_STATUS_FAILED)
            self.assertIn("synthetic apply failure", run.error_message or "")
            execution_state = db.scalar(
                select(ExecutionStrategyState).where(
                    ExecutionStrategyState.scope_kind == BACKTEST_SCOPE_KIND,
                    ExecutionStrategyState.scope_id == run_id,
                )
            )
            self.assertIsNotNone(execution_state)
            assert execution_state is not None
            self.assertEqual(execution_state.state_json, {})
            self.assertEqual(
                db.scalar(select(func.count()).select_from(RunTrace).where(RunTrace.run_id == run_id)),
                0,
            )

    def test_live_runtime_duplicate_activation_controls_signal_serialization_and_cleanup(self) -> None:
        skill = self.create_skill(title="Live Skill")
        response_payload = {
            "decision": {"action": "skip"},
            "reasoning_summary": "Stay flat.",
            "tool_calls": [],
            "provider": "mock-runner",
        }

        with self.session_factory() as db:
            service = LiveTaskService(db)
            created = service.create_task(skill.id)
            task_id = created["id"]
            self.assertEqual(created["status"], LIVE_STATUS_ACTIVE)

        with self.session_factory() as db:
            with self.assertRaises(LiveTaskOwnershipError) as exc_info:
                LiveTaskService(db).create_task(skill.id)
        self.assertEqual(exc_info.exception.existing_task_id, task_id)
        self.assertEqual(exc_info.exception.skill_id, skill.id)

        with (
            patch("app.services.live_service.SessionLocal", self.session_factory),
            patch(
                "app.services.live_service.build_market_snapshot_for_live",
                return_value={"market_candidates": [{"symbol": "BTC-USDT-SWAP"}], "provider": "mock-provider"},
            ),
            patch(
                "app.services.live_service.execute_agent_run_with_recovery",
                return_value=(response_payload, {"attempt_count": 1, "recovered": False, "retry_count": 0}),
            ),
        ):
            signal = execute_live_task(task_id, slot_as_of_ms=1_710_000_000_000, raise_on_reject=True)

        self.assertIsNotNone(signal)
        assert signal is not None
        self.assertEqual(signal["delivery_status"], "stored")
        self.assertEqual(signal["signal"]["action"], "skip")
        self.assertEqual(signal["signal"]["trigger_origin"], "manual")
        self.assertEqual(signal["signal"]["execution_time_ms"], 1_710_000_000_000)
        self.assertIn("portfolio_after", signal["signal"])
        self.assertEqual(signal["signal"]["fills"], [])

        with self.session_factory() as db:
            paused_payload = LiveTaskService(db).control_task(task_id, "pause")
            self.assertEqual(paused_payload["status"], LIVE_STATUS_PAUSED)

        with self.session_factory() as db:
            resumed_payload = LiveTaskService(db).control_task(task_id, "resume")
            self.assertEqual(resumed_payload["status"], LIVE_STATUS_ACTIVE)

        with self.session_factory() as db:
            stopped_payload = LiveTaskService(db).control_task(task_id, "stop")
            self.assertEqual(stopped_payload["status"], LIVE_STATUS_STOPPED)

        with self.session_factory() as db:
            LiveTaskService(db).delete_task(task_id)

        self.assertEqual(self.count_rows(LiveTask, LiveTask.id == task_id), 0)
        self.assertEqual(self.count_rows(LiveSignal, LiveSignal.live_task_id == task_id), 0)
        self.assertEqual(
            self.count_rows(
                PortfolioBook,
                PortfolioBook.scope_kind == LIVE_SCOPE_KIND,
                PortfolioBook.scope_id == task_id,
            ),
            0,
        )
        self.assertEqual(
            self.count_rows(
                ExecutionStrategyState,
                ExecutionStrategyState.scope_kind == LIVE_SCOPE_KIND,
                ExecutionStrategyState.scope_id == task_id,
            ),
            0,
        )

    def test_live_runtime_records_recovery_metadata_on_success(self) -> None:
        skill = self.create_skill(title="Live Recovery Skill")
        response_payload = {
            "decision": {"action": "skip", "reason": "Wait."},
            "reasoning_summary": "Recovered after retry.",
            "tool_calls": [],
            "provider": "mock-runner",
        }

        with self.session_factory() as db:
            task_id = LiveTaskService(db).create_task(skill.id)["id"]

        with (
            patch("app.services.live_service.SessionLocal", self.session_factory),
            patch(
                "app.services.live_service.build_market_snapshot_for_live",
                return_value={"market_candidates": [{"symbol": "BTC-USDT-SWAP"}], "provider": "mock-provider"},
            ),
            patch(
                "app.services.live_service.execute_agent_run_with_recovery",
                return_value=(response_payload, {"attempt_count": 2, "recovered": True, "retry_count": 1}),
            ),
        ):
            signal = execute_live_task(task_id, slot_as_of_ms=1_710_000_900_000, raise_on_reject=True)

        self.assertIsNotNone(signal)
        assert signal is not None
        self.assertEqual(signal["delivery_status"], "stored")
        self.assertEqual(signal["signal"]["recovery"]["attempt_count"], 2)
        self.assertTrue(signal["signal"]["recovery"]["recovered"])

        with self.session_factory() as db:
            task = db.get(LiveTask, task_id)
            self.assertIsNotNone(task)
            assert task is not None
            self.assertEqual(task.last_completed_slot_as_of_ms, 1_710_000_900_000)

    def test_live_runtime_failed_retry_keeps_task_active(self) -> None:
        skill = self.create_skill(title="Live Failure Skill")
        final_error = AgentRunnerRequestError(
            operation="run execution",
            status_code=503,
            detail=AgentRunnerErrorDetail(
                retryable=True,
                source="agent_runner",
                error_type="too_many_requests",
                message="Too Many Requests",
            ),
        )

        with self.session_factory() as db:
            task_id = LiveTaskService(db).create_task(skill.id)["id"]

        with (
            patch("app.services.live_service.SessionLocal", self.session_factory),
            patch(
                "app.services.live_service.build_market_snapshot_for_live",
                return_value={"market_candidates": [{"symbol": "BTC-USDT-SWAP"}], "provider": "mock-provider"},
            ),
            patch(
                "app.services.live_service.execute_agent_run_with_recovery",
                side_effect=AgentRunRecoveryError(attempt_count=3, final_error=final_error),
            ),
        ):
            signal = execute_live_task(task_id, slot_as_of_ms=1_710_001_800_000, raise_on_reject=True)

        self.assertIsNotNone(signal)
        assert signal is not None
        self.assertEqual(signal["delivery_status"], "failed")
        self.assertEqual(signal["signal"]["recovery"]["attempt_count"], 3)
        self.assertTrue(signal["signal"]["recovery"]["retryable"])

        with self.session_factory() as db:
            task = db.get(LiveTask, task_id)
            self.assertIsNotNone(task)
            assert task is not None
            self.assertEqual(task.status, LIVE_STATUS_ACTIVE)
            self.assertIsNone(task.last_completed_slot_as_of_ms)

    def test_live_runtime_rolls_back_state_patch_when_execution_fails_after_agent_response(self) -> None:
        skill = self.create_skill(title="Live State Rollback")
        response_payload = {
            "decision": {
                "action": "skip",
                "reason": "Only persist state after a successful live cycle.",
                "state_patch": {"focus_symbol": "ETH-USDT-SWAP", "last_action": "watch"},
            },
            "reasoning_summary": "Prepared a staged state update.",
            "tool_calls": [],
            "provider": "mock-runner",
        }

        with self.session_factory() as db:
            task_id = LiveTaskService(db).create_task(skill.id)["id"]

        with (
            patch("app.services.live_service.SessionLocal", self.session_factory),
            patch(
                "app.services.live_service.build_market_snapshot_for_live",
                return_value={"market_candidates": [{"symbol": "ETH-USDT-SWAP"}], "provider": "mock-provider"},
            ),
            patch(
                "app.services.live_service.execute_agent_run_with_recovery",
                return_value=(response_payload, {"attempt_count": 1, "recovered": False, "retry_count": 0}),
            ),
            patch(
                "app.services.live_service.PortfolioEngine.apply_decision",
                side_effect=RuntimeError("synthetic live apply failure"),
            ),
        ):
            signal = execute_live_task(task_id, slot_as_of_ms=1_710_002_700_000, raise_on_reject=True)

        self.assertIsNotNone(signal)
        assert signal is not None
        self.assertEqual(signal["delivery_status"], "failed")
        self.assertIn("synthetic live apply failure", signal["signal"]["error_message"] or "")

        with self.session_factory() as db:
            execution_state = db.scalar(
                select(ExecutionStrategyState).where(
                    ExecutionStrategyState.scope_kind == LIVE_SCOPE_KIND,
                    ExecutionStrategyState.scope_id == task_id,
                )
            )
            self.assertIsNotNone(execution_state)
            assert execution_state is not None
            self.assertEqual(execution_state.state_json, {})

    def test_trace_serializer_preserves_legacy_execution_timing(self) -> None:
        skill = self.create_skill(title="Legacy Timing Skill")
        run_id = self.make_id("bt")
        trace_id = self.make_id("trace")

        with self.session_factory() as db:
            run = BacktestRun(
                id=run_id,
                skill_id=skill.id,
                status=BACKTEST_STATUS_COMPLETED,
                scope="historical",
                start_time=datetime(2024, 1, 1, tzinfo=timezone.utc),
                end_time=datetime(2024, 1, 1, 0, 15, tzinfo=timezone.utc),
                initial_capital=10_000.0,
                benchmark_name="mock-benchmark",
                total_trigger_count=1,
                completed_trigger_count=1,
                summary_json={"total_return_pct": 0.0},
            )
            trace = RunTrace(
                id=trace_id,
                run_id=run_id,
                mode="backtest",
                trace_index=0,
                trigger_time=datetime(2024, 1, 1, 0, 15, tzinfo=timezone.utc),
                decision_json={
                    "action": "skip",
                    "_execution_timing": {
                        "started_at_ms": 1704067200000,
                        "completed_at_ms": 1704067200042,
                        "duration_ms": 42,
                    },
                },
                reasoning_summary="Legacy timing payload.",
                tool_calls_json=[],
            )
            db.add_all([run, trace])
            db.commit()
            db.refresh(trace)

            payload = trace_to_dict(trace)

        self.assertEqual(payload["execution_timing"]["duration_ms"], 42)
        self.assertIsNone(payload["execution_breakdown"])
        self.assertEqual(payload["llm_rounds"], [])
        self.assertNotIn("_execution_timing", payload["decision"])

    def test_market_sync_loop_dispatches_only_on_successful_coverage_advance(self) -> None:
        dispatcher = MagicMock(return_value=[])
        base_result = {
            "started_at_ms": 1_710_000_000_000,
            "completed_at_ms": 1_710_000_000_500,
            "coverage_start_ms_before": 1_709_999_000_000,
            "coverage_end_ms_before": 1_710_000_000_000,
            "coverage_start_ms_after": 1_709_999_000_000,
            "inserted_rows": 12,
            "synced_symbols": 3,
            "failures": [],
            "cutoff_ms": 1_710_000_060_000,
        }
        success_result = MarketSyncSweepResult(
            success=True,
            status="succeeded",
            coverage_end_ms_after=1_710_000_060_000,
            advanced_coverage=True,
            error_message=None,
            **base_result,
        )
        manager = MarketSyncLoopManager(
            session_factory=self.session_factory,
            sync_runner=lambda _db: success_result,
            dispatcher=dispatcher,
        )

        manager.run_cycle_once()

        dispatcher.assert_called_once_with(1_710_000_060_000)
        snapshot = manager.get_snapshot()
        self.assertEqual(snapshot.last_sync_status, "succeeded")
        self.assertEqual(snapshot.last_successful_coverage_end_ms, 1_710_000_060_000)

        failed_failures = [{"base_symbol": "BTC-USDT-SWAP", "reason": "sync_error"}]
        for result in [
            MarketSyncSweepResult(
                success=True,
                status="no_advance",
                coverage_end_ms_after=1_710_000_060_000,
                advanced_coverage=False,
                error_message=None,
                **base_result,
            ),
            MarketSyncSweepResult(
                success=False,
                status="failed",
                coverage_end_ms_after=1_710_000_060_000,
                advanced_coverage=True,
                error_message="partial failure",
                **{**base_result, "failures": failed_failures},
            ),
        ]:
            dispatcher.reset_mock()
            manager = MarketSyncLoopManager(
                session_factory=self.session_factory,
                sync_runner=lambda _db, result=result: result,
                dispatcher=dispatcher,
            )
            manager.run_cycle_once()
            dispatcher.assert_not_called()

    def test_sync_driven_dispatch_aligns_slots_to_task_cadence(self) -> None:
        skill_one_minute = self.create_skill(title="One Minute Skill", cadence="1m")
        skill_fifteen_minute = self.create_skill(title="Fifteen Minute Skill", cadence="15m")
        coverage_end_ms = int(datetime(2024, 1, 1, 12, 34, tzinfo=timezone.utc).timestamp() * 1000)

        with self.session_factory() as db:
            db.add_all(
                [
                    LiveTask(
                        id=self.make_id("live"),
                        skill_id=skill_one_minute.id,
                        status=LIVE_STATUS_ACTIVE,
                        cadence="1m",
                        cadence_seconds=60,
                    ),
                    LiveTask(
                        id=self.make_id("live"),
                        skill_id=skill_fifteen_minute.id,
                        status=LIVE_STATUS_ACTIVE,
                        cadence="15m",
                        cadence_seconds=900,
                    ),
                ]
            )
            db.commit()

        with (
            patch("app.services.live_service.SessionLocal", self.session_factory),
            patch("app.services.live_service.execute_live_task") as execute_mock,
        ):
            dispatch_sync_driven_live_tasks(coverage_end_ms)

        called_slots = [call.kwargs["slot_as_of_ms"] for call in execute_mock.call_args_list]
        self.assertIn(coverage_end_ms, called_slots)
        expected_fifteen_minute_slot = int(datetime(2024, 1, 1, 12, 30, tzinfo=timezone.utc).timestamp() * 1000)
        self.assertIn(expected_fifteen_minute_slot, called_slots)

    def test_sync_driven_dispatch_retries_latest_missing_slot_without_backlog_replay(self) -> None:
        skill = self.create_skill(title="Recovery Slot Skill", cadence="15m")
        checkpoint_ms = int(datetime(2024, 1, 1, 12, 15, tzinfo=timezone.utc).timestamp() * 1000)
        first_retry_coverage_ms = int(datetime(2024, 1, 1, 12, 31, tzinfo=timezone.utc).timestamp() * 1000)
        second_retry_coverage_ms = int(datetime(2024, 1, 1, 12, 32, tzinfo=timezone.utc).timestamp() * 1000)
        later_coverage_ms = int(datetime(2024, 1, 1, 12, 46, tzinfo=timezone.utc).timestamp() * 1000)

        with self.session_factory() as db:
            db.add(
                LiveTask(
                    id=self.make_id("live"),
                    skill_id=skill.id,
                    status=LIVE_STATUS_ACTIVE,
                    cadence="15m",
                    cadence_seconds=900,
                    last_completed_slot_as_of_ms=checkpoint_ms,
                )
            )
            db.commit()

        with (
            patch("app.services.live_service.SessionLocal", self.session_factory),
            patch("app.services.live_service.execute_live_task") as execute_mock,
        ):
            dispatch_sync_driven_live_tasks(first_retry_coverage_ms)
            dispatch_sync_driven_live_tasks(second_retry_coverage_ms)
            dispatch_sync_driven_live_tasks(later_coverage_ms)

        observed_slots = [call.kwargs["slot_as_of_ms"] for call in execute_mock.call_args_list]
        expected_retry_slot = int(datetime(2024, 1, 1, 12, 30, tzinfo=timezone.utc).timestamp() * 1000)
        expected_latest_slot = int(datetime(2024, 1, 1, 12, 45, tzinfo=timezone.utc).timestamp() * 1000)
        self.assertEqual(observed_slots[:2], [expected_retry_slot, expected_retry_slot])
        self.assertEqual(observed_slots[-1], expected_latest_slot)

    def test_manual_trigger_requires_healthy_fresh_sync_and_pending_slot(self) -> None:
        skill = self.create_skill(title="Manual Trigger Skill", cadence="15m")
        coverage_end_ms = int(datetime(2024, 1, 1, 12, 34, tzinfo=timezone.utc).timestamp() * 1000)
        expected_slot_ms = int(datetime(2024, 1, 1, 12, 30, tzinfo=timezone.utc).timestamp() * 1000)

        with self.session_factory() as db:
            task_id = LiveTaskService(db).create_task(skill.id)["id"]

        healthy_snapshot = MarketSyncLoopSnapshot(
            market_sync_loop_running=True,
            last_sync_started_at_ms=1_710_000_000_000,
            last_sync_completed_at_ms=1_710_000_000_500,
            last_sync_status="succeeded",
            last_sync_error=None,
            last_successful_sync_completed_at_ms=int(datetime.now(timezone.utc).timestamp() * 1000),
            last_successful_coverage_end_ms=coverage_end_ms,
        )

        with (
            patch("app.services.live_service.SessionLocal", self.session_factory),
            patch("app.services.live_service.get_live_sync_gate_snapshot", return_value=healthy_snapshot),
            patch(
                "app.services.live_service.execute_live_task",
                return_value={
                    "id": self.make_id("sig"),
                    "live_task_id": task_id,
                    "trigger_time_ms": healthy_snapshot.last_successful_sync_completed_at_ms,
                    "delivery_status": "stored",
                    "signal": {"execution_time_ms": expected_slot_ms},
                    "created_at_ms": healthy_snapshot.last_successful_sync_completed_at_ms,
                },
            ) as execute_mock,
        ):
            trigger_live_task_manually(task_id)

        execute_mock.assert_called_once()
        self.assertEqual(execute_mock.call_args.kwargs["slot_as_of_ms"], expected_slot_ms)

        stale_snapshot = MarketSyncLoopSnapshot(
            market_sync_loop_running=True,
            last_sync_started_at_ms=1,
            last_sync_completed_at_ms=2,
            last_sync_status="succeeded",
            last_sync_error=None,
            last_successful_sync_completed_at_ms=1,
            last_successful_coverage_end_ms=coverage_end_ms,
        )
        with (
            patch("app.services.live_service.SessionLocal", self.session_factory),
            patch("app.services.live_service.get_live_sync_gate_snapshot", return_value=stale_snapshot),
        ):
            with self.assertRaises(LiveTaskTriggerRejectedError):
                trigger_live_task_manually(task_id)

        unhealthy_snapshot = MarketSyncLoopSnapshot(
            market_sync_loop_running=True,
            last_sync_started_at_ms=1,
            last_sync_completed_at_ms=2,
            last_sync_status="failed",
            last_sync_error="sync failure",
            last_successful_sync_completed_at_ms=int(datetime.now(timezone.utc).timestamp() * 1000),
            last_successful_coverage_end_ms=coverage_end_ms,
        )
        with (
            patch("app.services.live_service.SessionLocal", self.session_factory),
            patch("app.services.live_service.get_live_sync_gate_snapshot", return_value=unhealthy_snapshot),
        ):
            with self.assertRaises(LiveTaskTriggerRejectedError):
                trigger_live_task_manually(task_id)

        with self.session_factory() as db:
            task = db.get(LiveTask, task_id)
            self.assertIsNotNone(task)
            assert task is not None
            task.last_completed_slot_as_of_ms = expected_slot_ms
            db.add(task)
            db.commit()

        with (
            patch("app.services.live_service.SessionLocal", self.session_factory),
            patch("app.services.live_service.get_live_sync_gate_snapshot", return_value=healthy_snapshot),
        ):
            with self.assertRaises(LiveTaskTriggerRejectedError):
                trigger_live_task_manually(task_id)

    def test_manual_trigger_conflict_raises_error(self) -> None:
        skill = self.create_skill(title="Manual Conflict Skill", cadence="15m")
        coverage_end_ms = int(datetime(2024, 1, 1, 12, 34, tzinfo=timezone.utc).timestamp() * 1000)

        with self.session_factory() as db:
            task_id = LiveTaskService(db).create_task(skill.id)["id"]

        healthy_snapshot = MarketSyncLoopSnapshot(
            market_sync_loop_running=True,
            last_sync_started_at_ms=1,
            last_sync_completed_at_ms=2,
            last_sync_status="succeeded",
            last_sync_error=None,
            last_successful_sync_completed_at_ms=int(datetime.now(timezone.utc).timestamp() * 1000),
            last_successful_coverage_end_ms=coverage_end_ms,
        )

        with (
            patch("app.services.live_service.SessionLocal", self.session_factory),
            patch("app.services.live_service.get_live_sync_gate_snapshot", return_value=healthy_snapshot),
            patch("app.services.live_service.execute_live_task", side_effect=LiveTaskConflictError("busy")),
        ):
            with self.assertRaises(LiveTaskConflictError):
                trigger_live_task_manually(task_id)

    def test_delete_strategy_cascade_removes_linked_execution_artifacts(self) -> None:
        skill = self.create_skill(title="Cascade Skill")
        run_id = self.make_id("bt")
        task_id = self.make_id("live")
        trace_id = self.make_id("trace")

        with self.session_factory() as db:
            run = BacktestRun(
                id=run_id,
                skill_id=skill.id,
                status=BACKTEST_STATUS_COMPLETED,
                scope="historical",
                start_time=datetime(2024, 1, 1, tzinfo=timezone.utc),
                end_time=datetime(2024, 1, 1, 1, 0, tzinfo=timezone.utc),
                initial_capital=10_000.0,
                benchmark_name="mock-benchmark",
                total_trigger_count=1,
                completed_trigger_count=1,
                summary_json={"total_return_pct": 0.02},
            )
            trace = RunTrace(
                id=trace_id,
                run_id=run.id,
                mode="backtest",
                trace_index=0,
                trigger_time=datetime(2024, 1, 1, 0, 15, tzinfo=timezone.utc),
                decision_json={"action": "skip"},
                reasoning_summary="No trade.",
                tool_calls_json=[],
            )
            live_task = LiveTask(
                id=task_id,
                skill_id=skill.id,
                status=LIVE_STATUS_PAUSED,
                cadence="15m",
                cadence_seconds=900,
            )
            backtest_book = PortfolioBook(
                id=self.make_id("book"),
                skill_id=skill.id,
                scope_kind=BACKTEST_SCOPE_KIND,
                scope_id=run.id,
                initial_capital=10_000.0,
                cash_balance=10_000.0,
                equity=10_000.0,
                realized_pnl=0.0,
                unrealized_pnl=0.0,
            )
            live_book = PortfolioBook(
                id=self.make_id("book"),
                skill_id=skill.id,
                scope_kind=LIVE_SCOPE_KIND,
                scope_id=live_task.id,
                initial_capital=10_000.0,
                cash_balance=10_000.0,
                equity=10_000.0,
                realized_pnl=0.0,
                unrealized_pnl=0.0,
            )
            db.add_all(
                [
                    run,
                    trace,
                    TraceExecutionDetail(
                        id=self.make_id("ted"),
                        trace_id=trace.id,
                        portfolio_before_json={"account": {"equity": 10_000.0}},
                        portfolio_after_json={"account": {"equity": 10_000.0}},
                        fills_json=[],
                        mark_prices_json={},
                    ),
                    live_task,
                    LiveSignal(
                        id=self.make_id("sig"),
                        live_task_id=live_task.id,
                        trigger_time=datetime(2024, 1, 1, 0, 30, tzinfo=timezone.utc),
                        signal_json={"decision": {"action": "skip"}},
                        delivery_status="stored",
                    ),
                    StrategyState(
                        id=self.make_id("state"),
                        skill_id=skill.id,
                        state_json={"mode": "immutable"},
                    ),
                    ExecutionStrategyState(
                        id=self.make_id("estate"),
                        skill_id=skill.id,
                        scope_kind=BACKTEST_SCOPE_KIND,
                        scope_id=run.id,
                        state_json={},
                    ),
                    ExecutionStrategyState(
                        id=self.make_id("estate"),
                        skill_id=skill.id,
                        scope_kind=LIVE_SCOPE_KIND,
                        scope_id=live_task.id,
                        state_json={},
                    ),
                    backtest_book,
                    live_book,
                    PortfolioFill(
                        id=self.make_id("fill"),
                        book_id=backtest_book.id,
                        market_symbol="BTC-USDT-SWAP",
                        action="watch",
                        side="buy",
                        quantity=0.0,
                        price=0.0,
                        notional=0.0,
                        realized_pnl=0.0,
                        trigger_time_ms=1,
                        trace_index=0,
                        execution_reference="portfolio_book_fill",
                    ),
                    PortfolioFill(
                        id=self.make_id("fill"),
                        book_id=live_book.id,
                        market_symbol="BTC-USDT-SWAP",
                        action="watch",
                        side="buy",
                        quantity=0.0,
                        price=0.0,
                        notional=0.0,
                        realized_pnl=0.0,
                        trigger_time_ms=2,
                        trace_index=None,
                        execution_reference="portfolio_book_fill",
                    ),
                ]
            )
            db.commit()

            stored_skill = db.get(Skill, skill.id)
            self.assertIsNotNone(stored_skill)
            delete_strategy_cascade(db, stored_skill)
            db.commit()

        self.assertEqual(self.count_rows(Skill, Skill.id == skill.id), 0)
        self.assertEqual(self.count_rows(BacktestRun, BacktestRun.skill_id == skill.id), 0)
        self.assertEqual(self.count_rows(RunTrace, RunTrace.run_id == run_id), 0)
        self.assertEqual(self.count_rows(TraceExecutionDetail, TraceExecutionDetail.trace_id == trace_id), 0)
        self.assertEqual(self.count_rows(LiveTask, LiveTask.skill_id == skill.id), 0)
        self.assertEqual(self.count_rows(LiveSignal, LiveSignal.live_task_id == task_id), 0)
        self.assertEqual(self.count_rows(PortfolioBook, PortfolioBook.skill_id == skill.id), 0)
        self.assertEqual(self.count_rows(ExecutionStrategyState, ExecutionStrategyState.skill_id == skill.id), 0)
        self.assertEqual(self.count_rows(StrategyState, StrategyState.skill_id == skill.id), 0)


if __name__ == "__main__":
    unittest.main()
