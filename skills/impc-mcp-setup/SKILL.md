---
name: impc-mcp-setup
description: Configure and verify one or more hosted IMPC MCP servers in the current or user-specified MCP-capable AI client. This is primarily a prerequisite invoked by another IMPC skill to install the specific Solr, Publications, Orthology or Allele server it needs; it can also be run directly when a user asks to set up, enable, repair or check an IMPC MCP server or "IMPC tools."
---

# IMPC MCP Server Setup

## What this actually is

The IMPC hosts four MCP servers at EBI. They are already running, they are public, and they need no authentication or local install. "Setting up the IMPC MCP servers" means adding their endpoints through the target client's native MCP configuration mechanism, then confirming that the client loaded the tools.

That framing matters because it tells you where things go wrong. The endpoints are almost never the problem. The problems are: picking the wrong client, writing to the wrong config file, using the wrong transport, silently creating duplicate entries, and — most often — the user expecting new tools to appear in a session that started before the config changed.

## The four servers

| Name | URL | Gives you |
| --- | --- | --- |
| `impc-solr` | `https://www.ebi.ac.uk/mi/impc/mcp/solr/` | Direct Solr querying across IMPC cores (`solr_query`) |
| `impc-publications` | `https://www.ebi.ac.uk/mi/impc/mcp/publication/` | IMPC-linked literature search by query or date |
| `impc-orthology` | `https://www.ebi.ac.uk/mi/impc/mcp/orthology/` | Mouse↔human ortholog mapping by symbol, MGI ID or HGNC ID |
| `impc-allele` | `https://www.ebi.ac.uk/mi/impc/mcp/allele/` | Allele records and product availability (mice, ES cells, CRISPR, vectors) |

All four use **Streamable HTTP** transport. Not SSE, not stdio. A client configured for SSE will fail to connect even though the URL is correct.

Keep the trailing slash on every URL, and use these exact hyphenated names — they are the ones the official IMPC documentation uses, so they are what collaborators following the public setup page will have.

Use these names as the server names in client configuration. After setup and reload, use the selected client's native server/tool list to identify the callable tools. Tool naming may differ between clients.

`references/servers.md` has the full tool inventory per server if the user wants to know what they are getting, or if you need to map a task ("find the human ortholog of Pax6") onto the right server.

## Workflow

### 1. Select the target client from runtime context

Use this precedence:

1. If the user names the client they want to configure, use that client. This overrides the client running the skill.
2. Otherwise, use the client identity provided by the current runtime or host application. An agent running in Codex should select Codex; one running in Claude Code should select Claude Code; one embedded in Cursor or VS Code should select that host.
3. Ask which client only when neither the request nor the runtime identifies it reliably.

Do not choose a client from incidental filesystem or PATH evidence. A repository can contain `.claude/`, `.cursor/`, `.codex/` and `.vscode/` configuration at the same time, and several client CLIs may be installed on one machine. Those artifacts help locate configuration only *after* the target client is known.

After selection, read only the matching section of `references/clients.md`. Do not present commands, paths, scope choices or restart instructions for a different client. If the selected client is not listed, use the generic MCP-client section.

### 2. Inspect the selected client's existing state

Use that client's native inspection method: its MCP command, settings UI, or documented configuration file. The matching section of `references/clients.md` gives the supported method and scope choices.

"Set up the IMPC servers" is often not a clean install. People arrive with two of the four already there, all four under an SSE transport that never worked, or names such as `impc_solr` that other skills cannot call. Adding a fresh set on top produces duplicates. If everything requested is already present and healthy, report that and stop.

If the client supports user/global and project/workspace scopes, preserve an
explicitly requested scope. Otherwise, default to project/workspace scope. Ask
the user to choose between project/workspace and user/global scope only when
the active project cannot be identified or the request makes the intended
scope ambiguous. If project/workspace scope is unsupported, explain that only
user/global scope is available and ask permission before using it; never
silently fall back to user/global scope. When the user asks for instructions
for somebody else's client, provide those instructions without modifying the
current machine.

### 3. Propose the client-native change, then apply it

Use only the selected client's section in `references/clients.md`. Prefer its supported settings UI or configuration command when available; edit a file when that is the documented mechanism or the user requests it.

Before changing configuration, state the selected scope, show the exact
command, UI operation or file edit, and get confirmation. Read and merge
existing file-based configuration so unrelated MCP servers survive. Do not
replace a whole configuration file just to add IMPC entries.

Four is the default, not a requirement. When another skill invoked this one as a prerequisite, it will have named the server it needs — install that one, confirm it, and hand control back rather than expanding the job. Adding the other three is a reasonable thing to offer, never a reason to make someone wait longer for the tool they were actually after.

### 4. Verify, and be honest about what verification proves

Verification has two layers, and conflating them is what makes this task feel broken when it isn't.

**The config is right.** Use the selected client's native server list, settings panel, or reread the configuration you changed. Confirm the requested names, URLs, HTTP transport and absence of duplicates.

**The tools actually work.** Follow the selected client's reload or restart instruction in `references/clients.md`; do not assume every client refreshes MCP configuration the same way. If the current session cannot load newly added servers, say so plainly and tell the user exactly what must be restarted or reloaded.

After the restart, the honest test is to call one: ask for the human ortholog of a mouse gene, or a small `solr_query`. A tool that returns data is proof; a tool merely appearing in a list is not, since a server can register and still fail on first call.

Tell the user the selected client's reload or restart requirement explicitly, before they discover it. "I added them and nothing happened" is overwhelmingly the most common way this task succeeds while looking like it failed, and a user who was warned reads a missing tool list as expected rather than as a fault.

If you want to confirm the servers themselves are up before blaming the config — worth doing when nothing works and you need to separate an EBI outage from a local mistake — a plain request will tell you:

```bash
curl -s -o /dev/null -w '%{http_code}\n' -X POST https://www.ebi.ac.uk/mi/impc/mcp/solr/ \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"check","version":"1"}}}'
```

`200` means that server is alive and the problem is local. Anything else, or a hang, points outward — see the last two troubleshooting entries. Swap the path for `publication`, `orthology` or `allele` to check the others. Run this yourself as a diagnostic; it is not something to hand the user as a setup step.

## Troubleshooting

**Tools not in the list after restart or reload.** Reconfirm the selected client, then use that client's native inspection method. Check that the configuration was written at a scope the active project or profile actually reads. If the client shows a pending trust or approval prompt, have the user approve the server in that client.

**Connects but every call errors.** Almost always transport: the entry says `sse` or defaulted to stdio. Streamable HTTP is the only supported transport — correct the entry using the selected client's native method.

**404 or hangs.** Check the trailing slash and that the path is `publication` (singular) while the server name is `impc-publications` (plural). That mismatch is in the official docs and trips people up.

**All four unreachable.** Test plain connectivity to `https://www.ebi.ac.uk/`. Corporate proxies and VPNs that intercept TLS break the streaming connection while ordinary browsing still works. If the site is fine but MCP is not, EBI may be in maintenance — the servers are hosted, so there is nothing local to fix; wait and retry.

**Duplicates after repeated setup attempts.** Use the selected client's remove action or delete only the stale key from its JSON/TOML configuration, then add the server once at the intended scope.

## Notes

- Never add credentials, API keys or auth headers. These servers are public; a client that prompts for authentication has been misconfigured as an OAuth server.
- Source of truth for the endpoints: https://www.mousephenotype.org/help/mcp-services/setup-instructions/ — check it if a URL stops working, since the servers are versioned and hosted by EBI.
