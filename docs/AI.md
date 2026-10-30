# AI gateway

REZE Intelligence talks to providers over their official HTTP APIs using the
Python standard library. No provider SDK is installed, and AI is always optional.

## 1. Configuration

```dotenv
REZE_AI_PROVIDER=openai          # openai | anthropic | gemini | openai_compatible
REZE_AI_MODEL=gpt-4o-mini
REZE_AI_API_KEY=sk-...
REZE_AI_BASE_URL=                # required for openai_compatible, optional override
REZE_AI_TIMEOUT_SECONDS=60
REZE_AI_MAX_INPUT_CHARS=12000
REZE_AI_MAX_OUTPUT_TOKENS=900
REZE_AI_VISION=auto              # auto | on | off
REZE_AI_FALLBACK=                # provider:model,provider:model (explicit opt-in)
```

Defaults per provider when `REZE_AI_MODEL` is empty:
`openai` → `gpt-4o-mini`, `anthropic` → `claude-3-5-sonnet-latest`,
`gemini` → `gemini-1.5-flash`, `openai_compatible` → `local-model`.

Provider and model can also be changed with `.config set ai_provider ...` /
`.config set ai_model ...` or the panel. **The API key is environment-only.**

Endpoints used:

| Provider | Request |
| --- | --- |
| OpenAI | `POST {base}/chat/completions` |
| OpenAI-compatible | `POST {base}/chat/completions` (e.g. `http://127.0.0.1:8000/v1`) |
| Anthropic | `POST {base}/messages` (`x-api-key`, `anthropic-version: 2023-06-01`) |
| Gemini | `POST {base}/models/{model}:generateContent?key=...` |

## 2. Commands

| Command | Behaviour |
| --- | --- |
| `.ai <prompt>` | general completion; replied text is appended as context |
| `.summarize` | summarize a reply or arguments (≤8 bullets) |
| `.translate <language>` | translate replied or provided text |
| `.rewrite <style>` | `shorter`, `formal`, `casual`, `clearer`, `bullets` |
| `.digest [count]` | summarize the last N messages of the current chat (bounded) |
| `.describe` | describe a replied image with a vision-capable model |
| `.aiinfo` | provider, model, credential presence, limits — no secrets |

Every response footer reports provider/model, duration and token usage, and
states that AI output may be inaccurate.

## 3. Reliability

- Request timeouts (`REZE_AI_TIMEOUT_SECONDS`).
- Bounded retries: at most two, only for rate limits and timeouts, with
  exponential backoff (1s, 2.5s). Client errors are never retried.
- 5xx outages get a single retry.
- Errors are normalized: missing credentials (`AIConfigurationError`), invalid
  model/endpoint, rate limit/quota, provider outage, timeout, empty response.
- Input length is capped; output tokens are capped.
- Cancellation propagates through the task manager for AI-heavy commands.

## 4. Privacy

- Prompts and responses are **never logged**; only provider, model and prompt
  length are recorded.
- Nothing is sent to a provider unless you invoke a command (or an automation
  action you created and enabled).
- A local archive entry is written only for the actions you configure
  (`ai_summary` automations store their result locally).
- Fallback is disabled by default. When enabled, the response says
  `fallback` in its metadata, because a different provider may have seen the
  content.
- `.describe` uploads the replied image to the configured provider; it is an
  explicit user action and the response names the provider.

## 5. Vision

Vision is used only when both are true:

1. `REZE_AI_VISION` allows it (`auto` inspects the model name, `on` forces it,
   `off` disables it), and
2. the adapter knows the model accepts images (`gpt-4o`, `claude-3+`, `gemini`,
   or an explicit `vision`/`llava` marker).

If a text-only model is configured, `.describe` fails with a clear message
instead of pretending to see the image. Images are downscaled and re-encoded as
JPEG before upload.

## 6. AI agent and tool calling

`.agent` is a separate, **sensitive** feature (`ai_agent`, OFF by default). The
model never executes anything directly:

1. `.agent run <request>` asks the model for one JSON proposal
   (`{"tool": "...", "args": {...}}`) using only the allowlisted tools.
2. REZE parses the JSON strictly. Unknown tools, unknown fields, wrong types and
   oversized strings are rejected; nothing is executed.
3. A pending approval is stored with a random 6-digit code that expires after
   15 minutes (`ai_approvals`).
4. `.agent approve <code>` runs the tool **once**, as the owner, and writes an
   audit row (`ai_tool_audit`). `.agent deny <code>` discards it.
5. Turning `ai_agent` off invalidates pending approvals; an approval can never
   be reused.

Allowlisted tools in 3.0:

| Tool | Arguments | Feature gate | Daily cap |
| --- | --- | --- | --- |
| `memory.save` | `content`, `tags` | `memory` | 10 |
| `memory.search` | `query`, `limit` | `memory` | 20 |
| `task.add` | `title`, `project`, `priority` | `projects` | 10 |
| `timeline.add` | `title`, `body` | `timeline` | 10 |
| `features.list` | — | none | 20 |
| `budget.status` | — | none | 20 |

Calls also count against `REZE_AI_DAILY_BUDGET_CALLS` and the per-run ceiling
`REZE_AI_TOOL_MAX_CALLS`. `.agent history` shows the audit trail, `.agent budget`
shows today's usage.

Without a configured provider, `.agent` says "not configured" instead of
simulating an agent.

## 7. Model Council

`.council <question>` asks the primary provider and up to two fallback members
(`REZE_AI_FALLBACK=provider:model,provider:model`) and synthesizes one answer.
It is honest about the result:

- one member answering is reported as a single answer, not a consensus;
- failed members are listed instead of being hidden;
- at most three members are queried;
- it requires `model_council` to be enabled (sensitive, OFF by default);
- all members use the same `REZE_AI_API_KEY`, which is a documented limitation
  for mixed providers.

## 8. Insights, voice and documents

- `.insights [days]` computes local statistics (tasks, focus, expenses, timeline)
  without any network call. `.insights ai [days]` optionally asks the configured
  provider for a narrative.
- `.voice` (reply to a voice note, feature `voice_intelligence`) uploads the
  audio to the configured provider for transcription, capped by
  `REZE_VOICE_MAX_MB` (default 25) and `REZE_VOICE_MODEL` (default `whisper-1`).
  The transcript is stored locally in `voice_notes`.
- `.doc` (reply to a document, feature `document_intelligence`) extracts text
  locally and indexes it in `search_index`; `.doc search` queries that index.

All three say exactly which feature or credential is missing instead of
returning a placeholder.

## 9. Limitations

- No streaming, embeddings or structured output in this release. Tool calling is
  limited to the six allowlisted tools above.
- Token counts are whatever the provider reports; Gemini reports
  `promptTokenCount`/`candidatesTokenCount`.
- Prices and model availability change; Reze does not hardcode either.
- A provider may still log prompts on its side — read its policy before sending
  private content.
- The council uses one API key for every member.
