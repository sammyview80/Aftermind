from providers.llm.anthropic import AnthropicProvider


class FakeTextBlock:
    def __init__(self, text: str) -> None:
        self.type = "text"
        self.text = text


class FakeMessages:
    def __init__(self, content: str) -> None:
        self._content = content
        self.calls = []

    def create(self, model, max_tokens, messages):
        self.calls.append({"model": model, "max_tokens": max_tokens, "messages": messages})
        return type("Response", (), {"content": [FakeTextBlock(self._content)]})()


class FakeAnthropicClient:
    def __init__(self, content: str) -> None:
        self.messages = FakeMessages(content)


def test_complete_sends_prompt_and_returns_text_content():
    client = FakeAnthropicClient('{"action": "supersede"}')
    provider = AnthropicProvider(model="claude-sonnet-5", max_tokens=1024, client=client)

    result = provider.complete("CANDIDATE:\nWe switched to RabbitMQ.")

    assert result == '{"action": "supersede"}'
    call = client.messages.calls[0]
    assert call["model"] == "claude-sonnet-5"
    assert call["max_tokens"] == 1024
    assert call["messages"] == [{"role": "user", "content": "CANDIDATE:\nWe switched to RabbitMQ."}]


def test_complete_ignores_non_text_blocks():
    class FakeToolUseBlock:
        type = "tool_use"

    class FakeMessagesMixed:
        def create(self, model, max_tokens, messages):
            return type("Response", (), {"content": [FakeToolUseBlock(), FakeTextBlock("hello")]})()

    client = type("Client", (), {"messages": FakeMessagesMixed()})()
    provider = AnthropicProvider(client=client)

    assert provider.complete("prompt") == "hello"
