# Fork patch ledger

This ledger records behavioral patch contracts carried by this fork. A commit
hash is provenance, not proof that a patch is still needed: during an upstream
upgrade, compare behavior and focused tests, then keep only the smallest delta
that upstream still lacks.

## Upgrade procedure

1. Fetch the authoritative remote with `git fetch upstream` and test
   `upstream/main` in a throwaway worktree before replaying fork changes.
2. For every entry below, classify upstream behavior as **missing**,
   **partial**, or **equivalent**. Check the production call paths as well as
   unit helpers; a matching symbol or merged PR is not enough.
3. Replay a missing contract, shrink a partial patch to the remaining gap, or
   drop an equivalent patch. Focused tests passing on pure upstream are the
   required evidence for removal.
4. Use `git range-diff` across the old and upgraded fork series. Where history
   was rewritten or squashed, also compare patches (for example with stable
   `git patch-id`) rather than relying on SHAs or subjects.
5. Run each entry's focused tests, then verify the real CLI/container/gateway
   construction paths affected by the upgrade. Finish with the broader
   affected suites and inspect the complete production diff.

## Carried contracts

### Fork workflow policy

- **Provenance:** effective local commit
  `25049791a606a24b91ad61a64354b18b9fd5589f`.
- **Ownership:** intentionally fork-owned; not pending upstream.
- **Contract:** the fork retains its selected GitHub Actions surface and does
  not re-enable the upstream-only review-label, installer/E2E evidence,
  infographic, rerun-label, or OS-matrix workflows removed by this commit.
- **Removal:** only an explicit fork CI-policy decision can retire this entry.
  An upstream workflow rewrite is a review input, not automatic removal
  evidence.

### Deployment and gateway lifecycle controls

- **Provenance:** effective port
  `4212f123d22fbd8d34d37a2b9666139aab13cc8c`; historical source commits
  `88d420013`, `7b1bd718e`, `1491ce05d`, `9d91202d5`, and `107e1bea2`.
- **Ownership:** fork-owned unless upstream supplies behaviorally equivalent
  deployment controls.
- **Contract:** lifecycle notices can target a dedicated per-platform channel,
  fall back to the home channel, route through relay-fronted platforms, and
  suppress active-session shutdown notices without suppressing the lifecycle
  broadcast. Container boot must skip s6 gateway reconciliation for
  `HERMES_GATEWAY_NO_SUPERVISE` and `gateway run --no-supervise`. The final
  Docker stage defaults to the reviewed Debian 13 base while allowing an
  explicitly reviewed `HERMES_RUNTIME_BASE` replacement.
- **Removal:** pure upstream must pass
  `tests/gateway/test_config.py`,
  `tests/gateway/test_restart_notification.py`, and
  `tests/hermes_cli/test_container_boot.py`, including dedicated-channel,
  relay delivery, active-session suppression, and both supervision opt-outs.
  Also build the default image and the deployment's reviewed custom-base image.

### Docker inherited npm replacement

- **Provenance:** `857ff0cf42ad4f6882c083b8063f64a3e02ec42d`.
- **Ownership:** fork/deployment compatibility patch.
- **Contract:** when a custom final runtime base already contains npm, the
  image build removes that inherited npm tree before copying the pinned
  `node_source` npm tree. Docker directory merging must not produce a mixed
  npm installation; `npm` and `npx` must resolve to the copied version.
- **Removal:** an upstream Docker build must replace rather than merge an
  inherited npm installation. Verify with a fixture base containing a
  conflicting npm tree and run `npm --version`, `npx --version`, and a package
  install in the resulting image.

### Discord progress cleanup

- **Provenance:** effective local commit
  `defb0e5992dcaa29c18509b8ffbd356b0e0574b2`, adapted from upstream open PR
  [#42661](https://github.com/NousResearch/hermes-agent/pull/42661) by Hafiy
  Zakaria. Open PRs #30801 and #60450 are related duplicates; #42661 is the
  carried source.
- **Contract:** Discord implements `delete_message(chat_id, message_id)` for
  temporary progress cleanup, using cached-channel lookup with fetch fallback,
  deleting the fetched message, treating Discord unknown-message/10008 as
  already cleaned, and returning false for disconnected, missing-channel, or
  other failure paths.
- **Removal:** require equivalent live adapter behavior and
  `tests/gateway/test_discord_delete_message.py` passing on pure upstream. PR
  closure or a base-adapter method alone is not removal evidence.

### Discord managed-role self-mentions

- **Provenance:** local commits
  `c43fe48ff80665c58d589bae2f01b714d60c2fff`,
  `a20cdcb1acdd3d8cad19fb91a4ccba3551742fe8`, and
  `98f82f731055cedb6493abb01bb671bf1eff0531`; upstream open PR
  [#67876](https://github.com/NousResearch/hermes-agent/pull/67876) by
  su-record.
- **Contract:** a mention of this bot's Discord-managed integration role
  (`role.tags.bot_id`) satisfies self-mention admission, its `<@&ROLE_ID>`
  token is stripped before model ingress, ordinary roles and other bots'
  managed roles remain negative cases, and bot-authored live ingress observes
  the same rule.
- **Removal:** pure upstream must pass the managed-role recognition, stripping,
  negative-case, and live-ingress cases in
  `tests/gateway/test_discord_free_response.py`. Preserve the upstream
  contributor provenance if the patch is replayed or refreshed.

### Named custom-provider Codex App Server

- **Provenance:** local commit
  `8b9b4fde4f6592424f17d446f03f432d8108a69f`, adapted from upstream open PR
  [#75191](https://github.com/NousResearch/hermes-agent/pull/75191) by Kevin
  (cosin2077), for issue
  [#75186](https://github.com/NousResearch/hermes-agent/issues/75186). The local
  commit preserves Kevin's authorship and records all three upstream source
  commits.
- **Contract:** an explicitly configured named custom provider may opt into
  `model.openai_runtime: codex_app_server`; bare `custom` and built-in
  non-Codex providers may not. Hermes retains the `custom:` namespace, while
  Codex `thread/start` receives only the active model and canonical configured
  provider key (for example `modelProvider: codex-lb`) and resolves
  endpoint/auth from its own config. A live model/provider switch retires the
  stale App Server session before the next turn. Background review, curator,
  compression/title/vision and other auxiliary loops stay on the provider's
  configured Hermes transport; same-provider review remains full-review rather
  than routed. CLI, TUI/desktop, API, ACP, cron, Feishu-comment, and detached
  background construction retain `requested_provider`.
- **Removal:** pure upstream must pass
  `tests/run_agent/test_codex_app_server_integration.py`,
  `tests/agent/transports/test_codex_app_server_runtime.py`,
  `tests/run_agent/test_background_review_cost_controls.py`,
  `tests/agent/test_set_runtime_main_custom_provider.py`,
  `tests/agent/test_curator.py`,
  `tests/tui_gateway/test_make_agent_provider.py`,
  `tests/test_tui_gateway_server.py`,
  `tests/gateway/test_api_server.py`,
  `tests/acp_adapter/test_acp_commands.py`,
  `tests/cli/test_cli_approval_ui.py`, and
  `tests/gateway/test_feishu_comment.py`. Inspect the recorded `thread/start`
  payload to ensure it contains no Hermes base URL or credential, and exercise
  one real TUI/desktop or gateway session plus one auxiliary review path.

### Codex App Server write-failure retirement

- **Status:** upstream-open with fork hardening.
- **Provenance:** local commits
  `f2340caad0bc6a5d1c80a67a9dc665f9ea3cee04` and
  `64dc034cd195e456eccd15ea99bf7bc2f8c99499`, preserving fangliquanflq's
  authorship from upstream open PR
  [#83129](https://github.com/NousResearch/hermes-agent/pull/83129), plus fork
  hardening commits `f622c0aa34f5eef63f74f13294bfa25ab2581ec2` and
  `5428602b52bb79fe1339caf7224b9d9bd1767eef`, plus lifecycle hardening commit
  `83234966b7b398a418fd11d17bba58c88ccd68bc`.
- **Ownership:** temporarily carried until upstream provides the complete
  behavior. The fork hardening closes serialization, generic pipe-I/O,
  interrupt, compaction, and in-flight steer/finalization gaps discovered
  during independent review of the upstream patch.
- **Contract:** JSON serialization failures remain ordinary request errors and
  clean their pending RPC state without killing a healthy transport. Every
  actual App Server write failure is typed as a transport failure, clears the
  pending request, and makes the affected runtime or session non-reusable.
  Concurrent request, response, steer, and approval writes remain distinct
  complete JSON-RPC frames, including when the pipe accepts short writes.
  Response, steer, interrupt, compaction, and finalization paths propagate the
  retirement decision so the next turn starts a fresh App Server process.
  Agent and session interrupt state share one ordered claim boundary so a stop
  cannot be lost or leak into the next turn. Normal turns and native compaction
  remain attached for 6,000 seconds rather than detaching after ten minutes
  while Codex continues working.
- **Removal:** pure upstream must pass
  `tests/agent/transports/test_codex_app_server_runtime.py` and
  `tests/agent/transports/test_codex_app_server_session.py`, including circular
  serialization, `BrokenPipeError` and generic `OSError` writes, short and
  concurrent writes, pending-state cleanup, response write failure,
  steer/finalization races, interrupt failure, compaction failure, and the
  6,000-second default deadline. Pure upstream must also pass
  `tests/agent/test_codex_app_server_persist.py`,
  `tests/agent/test_interrupt_compat.py`, and
  `tests/run_agent/test_codex_app_server_integration.py`. Reproduce the
  original gateway symptom and verify that the failed session is retired
  before the following turn.
