from providers.llm.openai import OpenAIProvider


class FakeChoice:
    def __init__(self, content: str) -> None:
        self.message = type("Message", (), {"content": content})()


class FakeCompletions:
    def __init__(self, content: str) -> None:
        self._content = content
        self.calls = []

    def create(self, model, messages):
        self.calls.append({"model": model, "messages": messages})
        return type("Response", (), {"choices": [FakeChoice(self._content)]})()


class FakeChat:
    def __init__(self, content: str) -> None:
        self.completions = FakeCompletions(content)


class FakeOpenAIClient:
    def __init__(self, content: str) -> None:
        self.chat = FakeChat(content)


def test_complete_sends_prompt_and_returns_content():
    client = FakeOpenAIClient('{"action": "create"}')
    provider = OpenAIProvider(model="gpt-4o-mini", client=client)

    result = provider.complete("CANDIDATE:\nWe use Redis.")

    assert result == '{"action": "create"}'
    assert client.chat.completions.calls[0]["model"] == "gpt-4o-mini"
    assert client.chat.completions.calls[0]["messages"] == [
        {"role": "user", "content": "CANDIDATE:\nWe use Redis."}
    ]
