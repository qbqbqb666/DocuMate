import unittest
from unittest.mock import patch

from langchain_core.language_models.fake_chat_models import FakeListChatModel

from src.backend.agent.context import ModelProvider
from src.backend.agent.model_resolver import (
    ModelResolver,
    UnsupportedModelError,
)


class BindableFakeModel(FakeListChatModel):
    def bind_tools(self, tools, *, tool_choice=None, **kwargs):
        return self


class ModelResolverTest(unittest.TestCase):
    @patch("src.backend.agent.model_resolver.create_model")
    def test_builds_and_caches_complete_model_bundle(self, create_model) -> None:
        model = BindableFakeModel(
            responses=["unused"],
            profile={"max_input_tokens": 262_144},
        )
        create_model.return_value = model
        resolver = ModelResolver()

        first = resolver.resolve(
            ModelProvider.SILICONFLOW,
            "Qwen/Qwen3.5-4B",
        )
        second = resolver.resolve(
            ModelProvider.SILICONFLOW,
            "Qwen/Qwen3.5-4B",
        )

        self.assertIs(first, second)
        self.assertIs(first.model, model)
        self.assertIs(first.model_with_tools, model)
        self.assertIs(first.summarizer.model, model)
        create_model.assert_called_once_with(
            "siliconflow",
            "Qwen/Qwen3.5-4B",
            max_input_tokens=262_144,
        )

    @patch("src.backend.agent.model_resolver.create_model")
    def test_clear_cache_recreates_model_bundle(self, create_model) -> None:
        create_model.side_effect = [
            BindableFakeModel(
                responses=["first"],
                profile={"max_input_tokens": 262_144},
            ),
            BindableFakeModel(
                responses=["second"],
                profile={"max_input_tokens": 262_144},
            ),
        ]
        resolver = ModelResolver()
        first = resolver.resolve(
            ModelProvider.SILICONFLOW,
            "Qwen/Qwen3.5-4B",
        )

        resolver.clear_cache()
        second = resolver.resolve(
            ModelProvider.SILICONFLOW,
            "Qwen/Qwen3.5-4B",
        )

        self.assertIsNot(first, second)
        self.assertEqual(create_model.call_count, 2)

    def test_rejects_unregistered_model_before_creating_client(self) -> None:
        resolver = ModelResolver()

        with self.assertRaisesRegex(UnsupportedModelError, "尚未注册模型"):
            resolver.resolve(ModelProvider.DEEPSEEK, "unknown-model")


if __name__ == "__main__":
    unittest.main()
