
import pytest
from pydantic import ValidationError

from impress import PipelineSetup

from .test_manager_core import MockPipeline


class TestPipelineSetupConstruction:
    def test_all_fields(self):
        async def fn(p):
            pass

        setup = PipelineSetup(
            name="my_pipe",
            type=MockPipeline,
            config={"a": 1},
            kwargs={"b": 2},
            adaptive_fn=fn,
        )
        assert setup.name == "my_pipe"
        assert setup.type is MockPipeline
        assert setup.config == {"a": 1}
        assert setup.kwargs == {"b": 2}
        assert setup.adaptive_fn is fn

    def test_defaults(self):
        setup = PipelineSetup(name="p", type=MockPipeline)
        assert setup.config == {}
        assert setup.kwargs == {}
        assert setup.adaptive_fn is None

    def test_validate_type_rejects_non_subclass(self):
        with pytest.raises(ValidationError):
            PipelineSetup(name="p", type=str)

    def test_validate_type_rejects_non_type(self):
        with pytest.raises(ValidationError):
            PipelineSetup(name="p", type="not_a_class")

    def test_validate_type_accepts_subclass(self):
        class Sub(MockPipeline):
            pass

        setup = PipelineSetup(name="p", type=Sub)
        assert setup.type is Sub


class TestFromDict:
    def test_known_fields_separated(self):
        async def fn(p):
            pass

        data = {
            "name": "p1",
            "type": MockPipeline,
            "config": {"x": 1},
            "adaptive_fn": fn,
        }
        setup = PipelineSetup.from_dict(data)
        assert setup.name == "p1"
        assert setup.type is MockPipeline
        assert setup.config == {"x": 1}
        assert setup.adaptive_fn is fn
        assert setup.kwargs == {}

    def test_extra_keys_go_to_kwargs(self):
        data = {
            "name": "p1",
            "type": MockPipeline,
            "foo": "bar",
            "baz": 42,
        }
        setup = PipelineSetup.from_dict(data)
        assert setup.kwargs == {"foo": "bar", "baz": 42}

    def test_kwargs_key_in_dict_lands_in_kwargs(self):
        # "kwargs" is not a known field, so it ends up nested inside kwargs
        data = {
            "name": "p1",
            "type": MockPipeline,
            "kwargs": {"inner": "value"},
        }
        setup = PipelineSetup.from_dict(data)
        assert setup.kwargs == {"kwargs": {"inner": "value"}}

    def test_minimal_dict(self):
        setup = PipelineSetup.from_dict({"name": "p", "type": MockPipeline})
        assert setup.name == "p"
        assert setup.config == {}
        assert setup.kwargs == {}
        assert setup.adaptive_fn is None


class TestToDict:
    def test_basic_structure(self):
        setup = PipelineSetup(
            name="p1",
            type=MockPipeline,
            config={"c": 1},
        )
        d = setup.to_dict()
        assert d["name"] == "p1"
        assert d["type"] is MockPipeline
        assert d["config"] == {"c": 1}

    def test_adaptive_fn_omitted_when_none(self):
        setup = PipelineSetup(name="p", type=MockPipeline, adaptive_fn=None)
        d = setup.to_dict()
        assert "adaptive_fn" not in d

    def test_adaptive_fn_included_when_set(self):
        async def fn(p):
            pass

        setup = PipelineSetup(name="p", type=MockPipeline, adaptive_fn=fn)
        d = setup.to_dict()
        assert d["adaptive_fn"] is fn

    def test_kwargs_spread_into_result(self):
        setup = PipelineSetup(
            name="p",
            type=MockPipeline,
            kwargs={"foo": "bar", "num": 7},
        )
        d = setup.to_dict()
        assert d["foo"] == "bar"
        assert d["num"] == 7

    def test_roundtrip_from_dict(self):
        original = {
            "name": "rt",
            "type": MockPipeline,
            "config": {"k": "v"},
            "extra_param": 99,
        }
        setup = PipelineSetup.from_dict(original)
        d = setup.to_dict()
        assert d["name"] == "rt"
        assert d["type"] is MockPipeline
        assert d["extra_param"] == 99
