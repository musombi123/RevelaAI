from __future__ import annotations

"""RevelaAI response/context builder.

This module never searches the web and never generates model text. It consumes
live research supplied by the orchestrator and turns it into bounded evidence.
"""

from typing import Any


class ResponseEngine:
    def __init__(self, ltm=None, registry=None):
        self.ltm = ltm
        self.registry = registry

    def _clean_text(self, value: Any, max_words: int = 120) -> str:
        text = str(value or "").strip()
        if not text:
            return ""
        bad = ("skip to main content", "privacy policy", "cookie policy", "sign up", "log in", "loading...")
        if any(x in text.lower() for x in bad):
            return ""
        words = text.split()
        return " ".join(words[:max_words])

    def _memory_reasoning(self, text: str) -> list[str]:
        if self.ltm is None:
            return []
        try:
            rows = self.ltm.retrieve_text(text=text, k=3)
        except Exception:
            return []
        return [v for v in (self._clean_text(x, 80) for x in rows or []) if v]

    def _registry_reasoning(self, outputs=None) -> list[str]:
        if not isinstance(outputs, dict):
            return []
        result = []
        for name, value in outputs.items():
            try:
                if hasattr(value, "float"):
                    confidence = value.float().mean().item()
                    if abs(confidence) > 0.05:
                        result.append(f"{name}: confidence={confidence:.2f}")
            except Exception:
                continue
        return result

    def _online_reasoning(self, online_context) -> list[dict]:
        if isinstance(online_context, dict):
            sources = online_context.get("sources", [])
        else:
            sources = online_context or []
        if not isinstance(sources, list):
            return []
        cleaned = []
        for item in sources:
            if not isinstance(item, dict):
                continue
            body = self._clean_text(item.get("content") or item.get("snippet"), 140)
            title = self._clean_text(item.get("title"), 30)
            url = str(item.get("url") or "").strip()
            if not (body or title or url):
                continue
            cleaned.append({
                "title": title,
                "snippet": self._clean_text(item.get("snippet"), 80),
                "content": body,
                "url": url,
                "source": self._clean_text(item.get("source"), 20),
                "published": self._clean_text(item.get("published"), 20),
                "retrieved_at": str(item.get("retrieved_at") or ""),
                "freshness": str(item.get("freshness") or ""),
            })
        return cleaned

    def _needs_context(self, text: str, intent: str | None) -> bool:
        value = str(text or "").strip().lower()
        if not value or value in {"hi", "hello", "hey", "thanks", "thank you"}:
            return False
        if any(x in value for x in ("who are you", "what is your name", "introduce yourself", "what can you do")):
            return False
        return intent not in {"conversation", "casual", "greeting"}

    def build_context(
        self,
        text: str,
        intent: str | None = None,
        emotion: str | None = None,
        model_outputs=None,
        online_context=None,
        platform_context=None,
        specialist_context=None,
        system_prompt=None,
    ) -> dict:
        if not self._needs_context(text, intent):
            return {"context": "", "fallback": "I'll answer using my built-in knowledge.", "sources": [], "realtime": False}

        context: list[str] = []
        sources = self._online_reasoning(online_context)

        if intent:
            context.append(f"Intent: {intent}")
        if emotion:
            context.append(f"Emotion: {emotion}")

        if platform_context:
            value = self._clean_text(platform_context, 220)
            if value:
                context += ["", "Verified Platform Context:", value]

        if specialist_context:
            value = self._clean_text(specialist_context, 220)
            if value:
                context += ["", "Specialized Intelligence:", value]

        memory = self._memory_reasoning(text)
        if memory:
            context += ["", "Conversation Memory:"] + [f"- {x}" for x in memory]

        registry = self._registry_reasoning(model_outputs)
        if registry:
            context += ["", "Model Signals:"] + [f"- {x}" for x in registry]

        if sources:
            context += ["", "Live Web Evidence:"]
            for index, source in enumerate(sources, 1):
                context.append(f"[{index}] {source.get('title') or 'Untitled source'}")
                if source.get("source"):
                    context.append(f"Publisher: {source['source']}")
                if source.get("published"):
                    context.append(f"Published: {source['published']}")
                if source.get("retrieved_at"):
                    context.append(f"Retrieved: {source['retrieved_at']}")
                if source.get("url"):
                    context.append(f"URL: {source['url']}")
                if source.get("content"):
                    context.append(f"Evidence: {source['content']}")

        realtime = any(x.get("freshness") == "live" for x in sources)
        return {
            "context": "\n".join(context).strip(),
            "fallback": f"I'll answer your question about '{text}' using the information available to me.",
            "sources": sources,
            "realtime": realtime,
        }

    def generate(self, text: str, **kwargs) -> dict:
        return self.build_context(text=text, **kwargs)


__all__ = ["ResponseEngine"]
