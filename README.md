# remote-browser-tool

Remote Browser Tool orchestrates a large language model (LLM) together with a real browser. The agent can operate the browser automatically, hand control over to a human via VNC when needed, store selective memory between steps, and notify users about its progress.

## Features

- **Pluggable architecture** – swap the LLM provider, notification channel, or browser backend by implementing simple interfaces.
- **Playwright-powered browser** – launches Chromium with optional persistent profiles and exposes it via VNC (Xvfb + x11vnc) for manual intervention.
- **Structured LLM directives** – LLM responses are parsed into typed directives (`continue`, `wait`, `wait_for_user`, `finished`, `failed`) with rich browser actions.
- **User interaction portal** – lightweight HTTP page with a “Finished” button ensures the agent only resumes after manual tasks are completed.
- **Notification pipeline** – send events to the console (default) or extend with custom channels.
- **Memory management** – configurable rolling memory store keeps the most relevant notes for the LLM context.
- **Docker-ready** – build a container image with all system dependencies, including Playwright browsers and VNC tooling.

## Installation

```bash
pip install -e .[dev]
playwright install chromium
```

You may need `x11vnc` and `Xvfb` installed locally to expose the browser via VNC when running outside Docker.

## Quick start

Run a task directly from the command line:

```bash
remote-browser-tool run \
  --task "Research latest product updates" \
  --goal "Summarize findings in less than 200 words" \
  --llm-provider openai \
  --model gpt-4-turbo \
  --api-key $OPENAI_API_KEY \
  --enable-vnc --portal-port 8765
```

When the agent requests manual help, the console notifier prints connection details and the portal URL. Connect to the VNC endpoint (default `localhost:590X`) to control the browser and mark the step finished from the portal web page.

### YAML configuration

Create a configuration file to avoid lengthy command arguments:

```yaml
# task.yaml
task:
  description: "Book a train ticket from Paris to Berlin"
  goal: "Ticket purchased with confirmation number"
llm:
  provider: openai
  model: gpt-4o
browser:
  headless: false
  enable_vnc: true
portal:
  host: 0.0.0.0
  port: 8765
notifications:
  channel: console
memory_max_entries: 40
```

Run with:

```bash
remote-browser-tool run --config task.yaml
```

### Environment files and variables

The application also reads defaults from environment variables using the prefix
`REMOTE_BROWSER_TOOL_`. Copy `.env.example` to `.env` and adjust the values to
define reusable defaults:

```bash
cp .env.example .env
remote-browser-tool run --env-file .env
```

Any variables defined in the `.env` file are merged with values from YAML
configuration files or command line overrides. All nested fields use double
underscores (for example `REMOTE_BROWSER_TOOL_LLM__API_KEY`).

When running inside Docker, mount the `.env` file into `/app/.env` to keep the
same defaults for every container instance:

```bash
docker run --rm -it \
  --env-file .env \
  -v $(pwd)/.env:/app/.env:ro \
  remote-browser-tool \
  --help
```

The `--env-file` flag on the CLI is optional when the `.env` file resides in the
current working directory.

### Docker usage

Build the image:

```bash
docker build -t remote-browser-tool .
```

Run a container for a single task, forwarding the portal and VNC ports:

```bash
docker run --rm -it \
  --env-file .env \
  -v $(pwd)/task.yaml:/app/task.yaml:ro \
  -v $(pwd)/.env:/app/.env:ro \
  -p 8765:8765 -p 5900:5900 \
  remote-browser-tool \
  run --config /app/task.yaml
  

Mount a host directory with configuration or browser profiles as needed (e.g. `-v $(pwd)/data:/app/data`).

To keep a long-lived container with persistent environment variables, launch it
with an idle command and execute tasks when required:

```bash
docker run -d --name remote-browser-tool \
  --env-file .env \
  -v $(pwd)/.env:/app/.env:ro \
  -p 8765:8765 -p 5900:5900 \
  --entrypoint python \
  remote-browser-tool \
  -c "import time; time.sleep(10**12)"

docker exec -it remote-browser-tool remote-browser-tool run --config /app/task.yaml
```

The second command reuses the environment from the running container, so tasks
can be executed repeatedly without restarting the image.

## Extending the tool

Implement custom providers by subclassing the relevant base classes:

- `remote_browser_tool.llm.base.LLMClient` for new LLM backends.
- `remote_browser_tool.browser.base.BrowserSession` for different browsers or remote drivers.
- `remote_browser_tool.notifications.base.Notifier` for email, messaging apps, etc.
- `remote_browser_tool.user_portal.base.UserInteractionPortal` for bespoke manual-intervention flows.

Register your implementations in `remote_browser_tool.factory` or replace the factory entirely when wiring your application.

## Development

Run the automated tests:

```bash
pytest
```

Format and lint the code with Ruff:

```bash
ruff check .
```

