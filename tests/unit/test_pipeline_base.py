import asyncio

import pytest

from impress.pipelines.impress_pipeline import ImpressBasePipeline


class MinimalPipeline(ImpressBasePipeline):
    """Minimal concrete subclass for testing the base class."""

    async def run(self):
        pass

    def register_pipeline_tasks(self):
        pass


class TestImpressBasePipelineInit:
    def test_name_set(self):
        p = MinimalPipeline(name="p1")
        assert p.name == "p1"

    def test_flow_defaults_to_none(self):
        p = MinimalPipeline(name="p1")
        assert p.flow is None

    def test_flow_passed_through(self):
        sentinel = object()
        p = MinimalPipeline(name="p1", flow=sentinel)
        assert p.flow is sentinel

    def test_state_is_empty_dict(self):
        p = MinimalPipeline(name="p1")
        assert p.state == {}

    def test_kill_parent_false(self):
        p = MinimalPipeline(name="p1")
        assert p.kill_parent is False

    def test_invoke_adaptive_step_false(self):
        p = MinimalPipeline(name="p1")
        assert p.invoke_adaptive_step is False

    def test_adaptive_barrier_is_event(self):
        p = MinimalPipeline(name="p1")
        assert isinstance(p._adaptive_barrier, asyncio.Event)

    def test_incoming_child_pipeline_request_empty(self):
        p = MinimalPipeline(name="p1")
        assert not p.incoming_child_pipeline_request

    def test_kwargs_stored_in_config(self):
        p = MinimalPipeline(name="p1", foo="bar", baz=42)
        assert p.config["foo"] == "bar"
        assert p.config["baz"] == 42


class TestChildPipelineRequest:
    def test_submit_sets_request(self):
        p = MinimalPipeline(name="p1")
        config = {"name": "child", "type": MinimalPipeline}
        p.submit_child_pipeline_request(config)
        assert p.incoming_child_pipeline_request == config

    def test_get_returns_config_then_clears(self):
        p = MinimalPipeline(name="p1")
        config = {"name": "child", "type": MinimalPipeline}
        p.submit_child_pipeline_request(config)

        result1 = p.get_child_pipeline_request()
        assert result1 == config

        result2 = p.get_child_pipeline_request()
        assert result2 is None

    def test_get_returns_none_when_nothing_pending(self):
        p = MinimalPipeline(name="p1")
        assert p.get_child_pipeline_request() is None

    def test_get_clears_after_retrieval(self):
        p = MinimalPipeline(name="p1")
        p.submit_child_pipeline_request({"name": "c"})
        p.get_child_pipeline_request()
        assert not p.incoming_child_pipeline_request


class TestAdaptiveStep:
    @pytest.mark.asyncio
    async def test_run_adaptive_step_sets_flag(self):
        p = MinimalPipeline(name="p1")
        # wait=False: flag is set without blocking on the barrier
        await p.run_adaptive_step(wait=False)
        assert p.invoke_adaptive_step is True

    @pytest.mark.asyncio
    async def test_run_adaptive_step_no_wait_does_not_hang(self):
        p = MinimalPipeline(name="p1")
        # _adaptive_barrier is clear — with wait=False this must return immediately
        await asyncio.wait_for(p.run_adaptive_step(wait=False), timeout=1.0)
        assert p.invoke_adaptive_step is True

    def test_set_adaptive_flag_true_clears_barrier(self):
        p = MinimalPipeline(name="p1")
        p._adaptive_barrier.set()
        p._set_adaptive_flag(True)
        assert p.invoke_adaptive_step is True
        assert not p._adaptive_barrier.is_set()

    def test_set_adaptive_flag_false_does_not_touch_barrier(self):
        p = MinimalPipeline(name="p1")
        p._adaptive_barrier.set()
        p._set_adaptive_flag(False)
        assert p.invoke_adaptive_step is False
        assert p._adaptive_barrier.is_set()  # barrier unchanged


class TestOptionalMethods:
    @pytest.mark.asyncio
    async def test_finalize_is_noop(self):
        p = MinimalPipeline(name="p1")
        result = await p.finalize()
        assert result is None

    @pytest.mark.asyncio
    async def test_get_scores_map_returns_empty_dict(self):
        p = MinimalPipeline(name="p1")
        scores = await p.get_scores_map()
        assert scores == {}

    def test_get_current_config_has_name_and_type(self):
        p = MinimalPipeline(name="p1")
        cfg = p.get_current_config_for_next_pipeline()
        assert "name" in cfg
        assert "type" in cfg

    def test_get_current_config_type_is_class(self):
        p = MinimalPipeline(name="p1")
        cfg = p.get_current_config_for_next_pipeline()
        assert cfg["type"] is MinimalPipeline


class TestAbstractMethods:
    def test_cannot_instantiate_without_run(self):
        class NoRun(ImpressBasePipeline):
            def register_pipeline_tasks(self):
                pass

        with pytest.raises(TypeError):
            NoRun(name="x")

    def test_cannot_instantiate_without_register(self):
        class NoRegister(ImpressBasePipeline):
            async def run(self):
                pass

        with pytest.raises(TypeError):
            NoRegister(name="x")
