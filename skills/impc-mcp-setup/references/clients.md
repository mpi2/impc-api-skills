# Per-client configuration

Use only the section for the target client chosen in `SKILL.md`. The user's explicit target wins; otherwise the runtime's own client identity wins. Config files and installed CLIs are not client-selection signals because several clients can coexist in one workspace.

All clients point at the same four endpoints with Streamable HTTP transport and no authentication:

| Server name | URL |
| --- | --- |
| `impc-solr` | `https://www.ebi.ac.uk/mi/impc/mcp/solr/` |
| `impc-publications` | `https://www.ebi.ac.uk/mi/impc/mcp/publication/` |
| `impc-orthology` | `https://www.ebi.ac.uk/mi/impc/mcp/orthology/` |
| `impc-allele` | `https://www.ebi.ac.uk/mi/impc/mcp/allele/` |

Note the path for publications is `publication` (singular) while the conventional server name is `impc-publications` (plural). Copy the URLs rather than retyping them.

**When editing any config file: read it first and merge.** These files usually already contain the user's other MCP servers. Add the four IMPC keys alongside them.

---

## Codex clients (Codex app / ChatGPT desktop app, Codex CLI, and Codex IDE extension)

These clients share MCP configuration on the same Codex host. Use `~/.codex/config.toml` for user scope or `.codex/config.toml` in a trusted project for project scope.

In the ChatGPT desktop app: Settings → MCP servers → Add server. Enter the exact server name, choose **Streamable HTTP**, paste its URL, save, then select **Restart**.

In the Codex IDE extension: gear menu → MCP servers → Add server. Enter the exact server name, choose **Streamable HTTP**, paste its URL, save, then select **Restart extension**.

For the CLI or a file-based change, merge these top-level tables into the selected config file:

```toml
[mcp_servers.impc-solr]
url = "https://www.ebi.ac.uk/mi/impc/mcp/solr/"

[mcp_servers.impc-publications]
url = "https://www.ebi.ac.uk/mi/impc/mcp/publication/"

[mcp_servers.impc-orthology]
url = "https://www.ebi.ac.uk/mi/impc/mcp/orthology/"

[mcp_servers.impc-allele]
url = "https://www.ebi.ac.uk/mi/impc/mcp/allele/"
```

A URL entry is Streamable HTTP. Inspect with `codex mcp list` or `/mcp` in the TUI. Start a new CLI session after changing the file. ChatGPT web does not read this local configuration; its MCP-backed tools come from installed plugins.

---

## Claude Code

Configurable by command. Preferred over hand-editing, because the CLI writes to the correct file for the scope and validates the entry.

```bash
claude mcp add --transport http --scope user impc-solr https://www.ebi.ac.uk/mi/impc/mcp/solr/
claude mcp add --transport http --scope user impc-publications https://www.ebi.ac.uk/mi/impc/mcp/publication/
claude mcp add --transport http --scope user impc-orthology https://www.ebi.ac.uk/mi/impc/mcp/orthology/
claude mcp add --transport http --scope user impc-allele https://www.ebi.ac.uk/mi/impc/mcp/allele/
```

Scopes: `--scope user` (all projects on this machine), `--scope project` (writes `.mcp.json` in the repo, committed and shared with teammates), `--scope local` (this project only, not shared; the default if `--scope` is omitted).

Inspect and remove:

```bash
claude mcp list              # names, URLs, connection status
claude mcp get impc-solr     # one server's config
claude mcp remove impc-solr  # remove
```

Project scope writes `.mcp.json` at the repo root:

```json
{
  "mcpServers": {
    "impc-solr": { "type": "http", "url": "https://www.ebi.ac.uk/mi/impc/mcp/solr/" },
    "impc-publications": { "type": "http", "url": "https://www.ebi.ac.uk/mi/impc/mcp/publication/" },
    "impc-orthology": { "type": "http", "url": "https://www.ebi.ac.uk/mi/impc/mcp/orthology/" },
    "impc-allele": { "type": "http", "url": "https://www.ebi.ac.uk/mi/impc/mcp/allele/" }
  }
}
```

Restart: start a new `claude` session. Project-scope servers may also require approval before they load; use `claude mcp list` or `/mcp` to inspect their state.

---

## Claude web, Claude Desktop, Cowork, or mobile

For an individual account: Customize → Connectors → `+` → Add custom connector. Enter the exact server name and URL, leave optional OAuth fields empty, and add it. Repeat for each requested server, then enable the connectors for the conversation.

For Team or Enterprise, only an Owner or Primary Owner may add a custom connector under Organization settings → Connectors; members connect it from Customize → Connectors after the owner adds it.

These remote connectors are account-backed across supported Claude web, desktop and mobile surfaces. Do not edit Claude Code's local configuration when the target is Claude web, Claude Desktop, Cowork or mobile.

---

## Cursor

Edit `.cursor/mcp.json` for the current project, or `~/.cursor/mcp.json` to make them available in every project:

```json
{
  "mcpServers": {
    "impc-solr": {
      "url": "https://www.ebi.ac.uk/mi/impc/mcp/solr/"
    },
    "impc-publications": {
      "url": "https://www.ebi.ac.uk/mi/impc/mcp/publication/"
    },
    "impc-orthology": {
      "url": "https://www.ebi.ac.uk/mi/impc/mcp/orthology/"
    },
    "impc-allele": {
      "url": "https://www.ebi.ac.uk/mi/impc/mcp/allele/"
    }
  }
}
```

Restart or reload Cursor, then check Settings → MCP that all requested servers show as connected.

---

## VS Code

Use **MCP: Add Server** from the Command Palette and choose Workspace or Global, or edit `.vscode/mcp.json` in the workspace:

```json
{
  "servers": {
    "impc-solr": { "type": "http", "url": "https://www.ebi.ac.uk/mi/impc/mcp/solr/" },
    "impc-publications": { "type": "http", "url": "https://www.ebi.ac.uk/mi/impc/mcp/publication/" },
    "impc-orthology": { "type": "http", "url": "https://www.ebi.ac.uk/mi/impc/mcp/orthology/" },
    "impc-allele": { "type": "http", "url": "https://www.ebi.ac.uk/mi/impc/mcp/allele/" }
  }
}
```

VS Code uses `servers` rather than `mcpServers`, and requires the explicit `"type": "http"`.

Inspect with **MCP: List Servers**. If Agent Host is enabled, prefer the guided flow or the portable workspace `.mcp.json` format documented by VS Code rather than assuming Agent Host reads `.vscode/mcp.json` directly.

---

## Any other MCP client

The generic shape is: name, URL, Streamable HTTP transport, no auth. If the client offers a transport dropdown, pick Streamable HTTP (sometimes labelled just "HTTP"). If it only offers SSE and stdio, it is too old for these servers — the connection will fail regardless of the URL.
