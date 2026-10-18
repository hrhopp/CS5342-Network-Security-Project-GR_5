"""Thin wrapper around the local LLM: messages in, text out.

Every generation setting comes from config, and nothing else in the codebase
talks to the model directly. Teammates (quiz agent, grader) call generate()
with their own system prompt and, if needed, their own temperature.

Usage:
    python -m rag.llm "Explain a SYN flood in two sentences."
"""
import sys
import time
from dataclasses import dataclass
from functools import lru_cache

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_ollama import ChatOllama

from rag import config


@dataclass
class LLMResult:
    text: str
    seconds: float
    prompt_tokens: int
    answer_tokens: int


@lru_cache(maxsize=8)
def _model(temperature: float, max_tokens: int, json_mode: bool) -> ChatOllama:
    return ChatOllama(
        model=config.LLM_MODEL,
        base_url=config.OLLAMA_BASE_URL,
        temperature=temperature,
        num_ctx=config.LLM_NUM_CTX,
        num_predict=max_tokens,
        keep_alive=config.LLM_KEEP_ALIVE,
        # Ollama constrains decoding to valid JSON: the 3B model otherwise
        # wraps JSON in prose or code fences that json.loads rejects.
        format="json" if json_mode else None,
    )


def generate(user: str, system: str | None = None,
             temperature: float = config.LLM_TEMPERATURE,
             max_tokens: int = config.LLM_MAX_TOKENS,
             json_mode: bool = False) -> LLMResult:
    """Send one prompt to the local model and return its reply plus timing.

    max_tokens: answer cap (the quiz agent needs more than a Q&A answer).
    json_mode:  force syntactically valid JSON output.
    """
    messages = ([SystemMessage(system)] if system else []) + [HumanMessage(user)]
    start = time.perf_counter()
    reply = _model(temperature, max_tokens, json_mode).invoke(messages)
    meta = reply.response_metadata or {}
    return LLMResult(
        text=str(reply.content).strip(),
        seconds=time.perf_counter() - start,
        prompt_tokens=meta.get("prompt_eval_count", 0),
        answer_tokens=meta.get("eval_count", 0),
    )


def main() -> int:
    prompt = " ".join(sys.argv[1:]) or "Explain a SYN flood in two sentences."
    r = generate(prompt)
    print(r.text)
    print(f"\n[{r.seconds:.1f}s | prompt {r.prompt_tokens} tokens | "
          f"answer {r.answer_tokens} tokens | "
          f"{r.answer_tokens / max(r.seconds, 1e-9):.1f} tokens/s overall]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
