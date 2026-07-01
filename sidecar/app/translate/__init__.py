"""Translation router and formatters.

Three-tier fallback (Ollama -> LM Studio -> OpenRouter), all OpenAI-compatible
behind one client that swaps base URL + key. TranslateGemma uses a fixed prompt
template; general models use normal instructions (CLAUDE.md gotcha #1).
Implemented in Session 3.
"""
