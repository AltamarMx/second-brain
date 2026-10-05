import asyncio
import base64
import json
from types import SimpleNamespace

import httpx
import pytest
from conftest import make_paper
from test_processing import FULLTEXT, TODAY, FakeBackend, processor

from second_brain.agents import sync_agents
from second_brain.ask import ask
from second_brain.backends import BackendError, get_backend
from second_brain.backends.anthropic_api import AnthropicApiBackend, strict_schema
from second_brain.backends.ollama import OllamaBackend
from second_brain.machines import MachineProfile
from second_brain.mcp_server import build_server
from second_brain.models import FullText

SCHEMA = {
    "type": "object",
    "properties": {"answer": {"type": "string", "pattern": "x"}},
    "required": ["answer"],
}


# --- Ollama ---------------------------------------------------------------------


def ollama_with(handler, num_ctx=8192):
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return OllamaBackend("gemma4", "http://ollama.test", num_ctx, client=client)


def test_ollama_request_and_reply(tmp_path):
    seen = {}

    def handler(request):
        seen.update(json.loads(request.content))
        return httpx.Response(200, json={"message": {"content": '{"answer": "hola"}'}})

    image = tmp_path / "p.png"
    image.write_bytes(b"PNGDATA")
    output, model = ollama_with(handler).run(
        "Pregunta", SCHEMA, stdin="texto " * 10_000, images=[image]
    )
    assert output == {"answer": "hola"} and model == "gemma4"
    assert (
        seen["format"] == SCHEMA and seen["options"]["num_ctx"] == 8192 and seen["stream"] is False
    )
    message = seen["messages"][0]
    assert message["images"] == [base64.b64encode(b"PNGDATA").decode()]
    assert "texto truncado" in message["content"]  # does not exceed the context window
    assert len(message["content"]) < (8192 - 6000) * 3 + 1000


def test_ollama_errors():
    with pytest.raises(BackendError, match="ollama pull"):
        ollama_with(lambda r: httpx.Response(404, text="not found")).run("p", SCHEMA)
    with pytest.raises(BackendError, match="JSON"):
        ollama_with(lambda r: httpx.Response(200, json={"message": {"content": "no json"}})).run(
            "p", SCHEMA
        )

    def offline(request):
        raise httpx.ConnectError("no", request=request)

    with pytest.raises(BackendError, match="no está abierto"):
        ollama_with(offline).run("p", SCHEMA)
    assert ollama_with(offline).running() is False


def test_get_backend_uses_profile():
    profile = MachineProfile.model_validate({"llm": {"model": "gemma4", "num_ctx": 16384}})
    backend = get_backend("ollama", profile)
    assert (backend.model, backend.num_ctx) == ("gemma4", 16384)
    with pytest.raises(BackendError, match=r"\[llm\]\.model"):
        get_backend("ollama", MachineProfile())
    with pytest.raises(BackendError, match="none"):
        get_backend("none")


# --- Anthropic API --------------------------------------------------------------


def test_strict_schema():
    schema = strict_schema(
        {
            "type": "object",
            "properties": {
                "a": {"type": "array", "minItems": 1, "items": {"type": "object", "properties": {}}}
            },
        }
    )
    assert schema["additionalProperties"] is False
    assert "minItems" not in schema["properties"]["a"]
    assert schema["properties"]["a"]["items"]["additionalProperties"] is False


class FakeStream:
    def __init__(self, message, calls, kwargs):
        self.message, self.calls = message, calls
        calls.append(kwargs)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get_final_message(self):
        return self.message


def fake_client(text='{"answer": "ok"}', stop_reason="end_turn"):
    calls = []
    message = SimpleNamespace(
        stop_reason=stop_reason,
        model="claude-opus-5-5",
        content=[SimpleNamespace(type="text", text=text)],
    )
    stream = lambda **kwargs: FakeStream(message, calls, kwargs)  # noqa: E731
    return SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(stream=stream))), calls


def test_anthropic_backend(tmp_path):
    client, calls = fake_client()
    image = tmp_path / "p.png"
    image.write_bytes(b"PNG")
    output, model = AnthropicApiBackend(client=client).run(
        "Pregunta", SCHEMA, stdin="texto", images=[image]
    )
    assert output == {"answer": "ok"} and model == "claude-opus-5-5"
    call = calls[0]
    assert call["model"] == "claude-opus-5-5" and call["fallbacks"] == "default"
    assert call["output_config"]["format"]["type"] == "json_schema"
    assert "pattern" not in json.dumps(call["output_config"]["format"]["schema"])
    content = call["messages"][0]["content"]
    assert content[0]["type"] == "image" and content[-1]["text"].startswith("Pregunta")


def test_anthropic_refusal():
    client, _ = fake_client(stop_reason="refusal")
    with pytest.raises(BackendError, match="declinó"):
        AnthropicApiBackend(client=client).run("p", SCHEMA)


# --- ask and MCP ----------------------------------------------------------------


@pytest.fixture
def processed(lib):
    lib.write_paper(make_paper(title="Night ventilation in Hermosillo"))
    lib.write_fulltext(
        FullText(
            citekey="garcia2021thermal",
            source_pdf_sha256="ab",
            extractor="x",
            extracted=TODAY,
            pages=3,
        ),
        FULLTEXT,
    )
    processor(lib).process("garcia2021thermal", figures=False)
    return lib


class AnswerBackend:
    name = "fake"

    def __init__(self):
        self.calls = []

    def run(self, prompt, schema, stdin="", images=None):
        self.calls.append(stdin)
        return {
            "answer": "Baja 2.5 °C [garcia2021thermal, p. 3].",
            "citekeys": ["garcia2021thermal"],
        }, "m"


def test_ask_sends_only_retrieved_material(processed):
    backend = AnswerBackend()
    answer = ask(processed, backend, "¿cuánto baja la temperatura pico con ventilación nocturna?")
    assert answer.citekeys == ["garcia2021thermal"]
    sent = backend.calls[0]
    assert "[garcia2021thermal, p. 3]" in sent and "Resumen:" in sent
    assert "[1] Smith" not in sent  # references are not material
    nothing = ask(processed, backend, "xyzzy")
    assert nothing.citekeys == [] and len(backend.calls) == 1


def test_mcp_server_tools(processed):
    server = build_server(processed.home)
    tools = {t.name for t in asyncio.run(server.list_tools())}
    assert {
        "search_papers",
        "get_paper",
        "get_fulltext",
        "export_bibtex",
        "create_project",
    } <= tools
    found = asyncio.run(server.call_tool("search_papers", {"query": "night ventilation"}))
    assert "garcia2021thermal" in str(found)
    text = asyncio.run(
        server.call_tool("get_fulltext", {"citekey": "garcia2021thermal", "pages": "3"})
    )
    assert "2.5" in str(text) and "page 1" not in str(text)
    asyncio.run(server.call_tool("create_project", {"slug": "tesis", "name": "Tesis"}))
    asyncio.run(
        server.call_tool("add_to_project", {"slug": "tesis", "citekeys": ["garcia2021thermal"]})
    )
    bib = asyncio.run(server.call_tool("export_bibtex", {"project": "tesis"}))
    assert "@article{garcia2021thermal" in str(bib)


def test_agents_sync_writes_opencode_and_keeps_user_providers(home):
    config = home / "opencode.json"
    data = json.loads(config.read_text())
    assert data["mcp"]["second-brain"]["command"][-1] == "sb-mcp"
    data["provider"]["openrouter"] = {"name": "mío"}
    config.write_text(json.dumps(data, indent=2) + "\n")
    sync_agents(home)
    merged = json.loads(config.read_text())
    assert "openrouter" in merged["provider"] and "ollama" in merged["provider"]
    assert (home / ".opencode" / "agents" / "bibliotecario.md").is_file()


def test_fake_backend_still_available():
    assert FakeBackend().name == "fake"
