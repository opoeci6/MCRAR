# Optional LLM (M7)

MCRAR works without an LLM. With one, using your own API key, it does two extra things:

1. **Reads each text search.** The rule parser runs first and keeps the hard constraints (BPM,
   vocals, duration, licence). The LLM then adds:
   - an English description of the sound for the audio model, so a search in another language
     works
   - genre and mood hints
   - an energy or tempo preference
   - Jamendo keywords for "Search Jamendo for more"
2. **Reranks the top results, but only when you click "Rerank top 20 with LLM".** The model
   reorders the top results and explains each one. It also gives a verdict on how well they fit.
   A `poor` verdict suggests a Jamendo import, even when the similarity score looked fine.

Code: `backend/src/mcrar/llm/` (providers), `recommend/llm_parse.py` and `recommend/llm_rerank.py`.

## Setting it up

In **Settings → LLM**:
1. Pick a provider and turn on "Use an LLM".
2. Paste the provider's API key.
3. Optionally choose a model. An empty field uses the provider's default.
   - **Load models** fetches the provider's model list (`GET {base_url}/models`, or the Anthropic
     models API), so you can pick a model in the model field or keep typing a name.
   - Nothing is fetched until you click it.
   - Models that can't chat are hidden: embedding, speech, image, video, moderation and
     realtime models. For OpenAI, the legacy completion models and the codex and `-pro` models
     (Responses API only) are hidden too.
   - A hidden model can still be typed.
   - Z.AI doesn't document a model list. A provider without one answers "This provider does not
     list its models".
4. Click **Test connection**.

The API key is stored like the Jamendo key: in `.secrets/secrets.toml` by default, or in the OS
keyring or an environment variable (`MCRAR_SECRET_LLM_API_KEY_<PRESET>`). Each provider has its
own key (`llm_api_key_<preset>`), so switching providers needs no re-typing. The other settings
are written to `config/settings.toml` under `[llm]`, and can be pinned with `MCRAR_LLM__*`
environment variables.

From the CLI:
- `mcrar llm status`
- `mcrar llm test`
- `mcrar llm models [--preset X] [--base-url U]`
- `mcrar search --llm "..."`
- `mcrar ratings eval --llm`: compares against the rules on your ratings.

| Preset | Base URL | Default model | JSON mode | Notes |
|---|---|---|---|---|
| OpenAI | `https://api.openai.com/v1` | `gpt-6-luna` | `json_schema` (strict) | `max_completion_tokens`, `reasoning_effort: none` |
| DeepSeek | `https://api.deepseek.com` | `deepseek-flash` | `json_object` | thinking turned off |
| SiliconFlow | `https://api.siliconflow.com/v1` | `deepseek-ai/DeepSeek-V3.2` | `json_object` | `enable_thinking: false`. For the China endpoint, set the base URL to `https://api.siliconflow.cn/v1` |
| Z.AI (GLM) | `https://api.z.ai/api/paas/v4` | `glm-5.3-flash` | `json_object` | GLM-5.3 always thinks (it cannot be turned off). China: `https://open.bigmodel.cn/api/paas/v4` |
| OpenRouter | `https://openrouter.ai/api/v1` | `openai/gpt-5-nano` | `json_schema` | |
| Google Gemini | `https://generativelanguage.googleapis.com/v1beta/openai` | `gemini-3.8-flash` | `json_schema` | `reasoning_effort: low` |
| Groq | `https://api.groq.com/openai/v1` | `openai/gpt-oss-20b` | `json_schema` | `reasoning_effort: low` |
| Anthropic | `https://api.anthropic.com` | `claude-haiku-5-5` | structured output | official `anthropic` SDK, `effort: low` |
| Other OpenAI-compatible | `http://localhost:11434/v1` (Ollama) | none: you must name one | `json_object` | key optional. Also LM Studio (`http://localhost:1234/v1`) or any regional endpoint |

The presets were checked against each provider's documentation on 2026-10-19.
- **Provider-specific flags.** The extras in the Notes column are sent only with the preset's
  default model, because they are model-specific.
- **JSON mode fallback.** When a service rejects the JSON mode with HTTP 400, the provider steps
  down (`json_schema` → `json_object` → none) and remembers what worked. The schema is always in
  the prompt too.
- **Validation.** Every reply is validated and clamped locally.

## Privacy and safety

- **What is sent.** Only the search text, the filters you set and, for a rerank, each track's
  title, artist, tags and measured values (BPM, key, energy, duration, vocal). It never sends
  audio, licence data, URLs, catalog ids or any key except the provider's own.
- **Untrusted text.** Track titles and tags come from third parties. They go in as a JSON block
  that the model is told to treat as data. Its reply can only reorder the given tracks and add
  capped plain text. A rerank cannot bypass the licence filter or the source filter, because it
  only reorders results that already passed them.
- **Keys stay secret.** Keys are never logged or returned by the API. Error messages are fixed
  text plus an HTTP status, never the provider's response body.
- **Testing other addresses.** `POST /api/llm/test` can test a provider with a base URL that is
  not saved yet, using that provider's saved key. Like every state-changing route, it refuses
  requests from web pages that are not on loopback (`docs/api.md`, security model).

## Speed, cost and fallback

- **The parse.**
  - It is cached per query text, filters and model: up to 256 entries, kept until the server
    restarts. Load more and the Jamendo import reuse it.
  - The default timeout is 10 s (`llm.parse_timeout_s`).
- **Fallback.**
  - When the parse fails (timeout, bad key, rate limit, invalid reply), the search uses the rule
    parser and notes why. The failure is remembered for 60 s, so the following searches don't
    each wait for the timeout.
  - A rerank failure shows the reason, and the list stays as it was.
- **Rerank limits.** The rerank timeout is 45 s (`llm.rerank_timeout_s`), and it reorders
  `llm.rerank_top_n` (default 20) results.
- **Cost.** A parse is about 1–2k input tokens and a rerank of 20 tracks about 3–5k. With a cheap
  model (`gpt-6-luna`, `deepseek-flash`, `claude-haiku-5-5`), both cost a small fraction of a
  cent.
