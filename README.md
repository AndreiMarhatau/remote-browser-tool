# remote-browser-tool

`remote-browser-tool` lets a large language model drive a real Chromium browser while you supervise from a web portal or VNC. It
ships with a Typer CLI, an executor API, and an admin interface so you can queue and inspect automated browsing tasks.

The steps below keep everything Docker-first so you can experiment without installing local Python dependencies.

## Start with the simplest setup

1. Build the image once:
   ```bash
   docker build -t remote-browser-tool .
   ```
2. Export the OpenAI settings (the executor uses them to talk to the model):
   ```bash
   export REMOTE_BROWSER_TOOL_LLM__PROVIDER=openai
   export REMOTE_BROWSER_TOOL_LLM__MODEL=gpt-4o-mini
   export REMOTE_BROWSER_TOOL_LLM__API_KEY=sk-...
   ```
3. Run a one-off task in an interactive container:
   ```bash
   docker run --rm -it \
    -e REMOTE_BROWSER_TOOL_LLM__PROVIDER \
    -e REMOTE_BROWSER_TOOL_LLM__MODEL \
    -e REMOTE_BROWSER_TOOL_LLM__API_KEY \
     -p 8765:8765 -p 5900:5900 \
     remote-browser-tool \
     run \
       --task "Try the remote browser tool" \
       --goal "Explain what happened in the portal when you finish"
   ```

The CLI prints both a browser portal URL and a VNC connection string whenever a manual step is required. Open them from your host
machine, complete the requested action, and click **Finished** in the portal to resume the run. Stop the task at any time with
`Ctrl+C`.

## Add what you need next

Each section below adds a small tweak. Pick the one you need and keep the rest of your setup unchanged.

### Reuse a task definition with a YAML file

1. Create `task.yaml` with your preferred defaults:
   ```yaml
   task:
     description: "Book a train ticket from Paris to Berlin"
     goal: "Ticket purchased with confirmation number"
   llm:
     provider: openai
     model: gpt-4o
   browser:
     enable_vnc: true
     headless: false
   portal:
     port: 8765
   memory_max_entries: 40
   ```
2. Mount the file when launching a task container:
   ```bash
    docker run --rm -it \
      -e REMOTE_BROWSER_TOOL_LLM__PROVIDER \
      -e REMOTE_BROWSER_TOOL_LLM__MODEL \
      -e REMOTE_BROWSER_TOOL_LLM__API_KEY \
      -v $(pwd)/task.yaml:/app/task.yaml:ro \
      -p 8765:8765 -p 5900:5900 \
      remote-browser-tool run --config /app/task.yaml
   ```

### Run the executor as a long-lived service

Keep the LLM key private to the executor—the admin portal does not need it.

```bash
docker network create remote-browser-tool || true

docker run -d --name rbt-executor \
  --network remote-browser-tool \
  -e REMOTE_BROWSER_TOOL_LLM__PROVIDER \
  -e REMOTE_BROWSER_TOOL_LLM__MODEL \
  -e REMOTE_BROWSER_TOOL_LLM__API_KEY \
  -p 9001:9001 -p 8765:8765 -p 5900:5900 \
  -v executor_artifacts:/app/executor_artifacts \
  remote-browser-tool executor --host 0.0.0.0 --port 9001
```

The service exposes:

- `http://localhost:9001` for API calls from the admin portal.
- `http://localhost:8765` for the user portal when a task is waiting on you.
- `localhost:5900` for the VNC bridge.

Stop the executor with `docker stop rbt-executor`.

### Launch the admin portal and attach executors

Run the admin UI on the same Docker network so it can reach your executors. No API key is required.

```bash
docker run --rm --name rbt-admin \
  --network remote-browser-tool \
  -p 8080:8080 \
  remote-browser-tool admin \
  --executor default=http://rbt-executor:9001 \
  --host 0.0.0.0 --port 8080
```

Open [http://localhost:8080](http://localhost:8080) to submit tasks and monitor progress. Add more executors by repeating the
`docker run` command above with a different container name and port, then passing additional `--executor label=url` options to the
admin command.

Want the admin without any executors yet? Start it alone and add executors later from the UI:

```bash
docker run --rm --name rbt-admin \
  -p 8080:8080 \
  remote-browser-tool admin --host 0.0.0.0 --port 8080
```

### Use Docker Compose for a persistent pair

If you prefer a single command that brings up both services and keeps artifacts in a named volume:

1. Copy the environment template and set your OpenAI settings (only the executor consumes them):
   ```bash
   cp .env.example .env
   cat <<'VARS' >> .env
REMOTE_BROWSER_TOOL_LLM__PROVIDER=openai
REMOTE_BROWSER_TOOL_LLM__MODEL=gpt-4o-mini
REMOTE_BROWSER_TOOL_LLM__API_KEY=sk-...
VARS
   ```
2. Start the services:
   ```bash
   docker compose up -d executor admin
   ```
3. Visit the admin UI at [http://localhost:8080](http://localhost:8080). Tear everything down when finished:
   ```bash
   docker compose down
   ```

Task artifacts live in the named volume `executor_artifacts`. Remove it with `docker compose down -v` if you want a clean slate.
You can also launch a single service (`docker compose up -d executor` or `docker compose up admin`) depending on what you need.

### Share environment defaults across commands

The CLI reads variables prefixed with `REMOTE_BROWSER_TOOL_...`. Update `.env` (or pass `-e` flags) with overrides such as:

```bash
REMOTE_BROWSER_TOOL_LLM__PROVIDER=openai
REMOTE_BROWSER_TOOL_LLM__MODEL=gpt-4o-mini
REMOTE_BROWSER_TOOL_BROWSER__HEADLESS=true
REMOTE_BROWSER_TOOL_BROWSER__ENABLE_VNC=false
REMOTE_BROWSER_TOOL_PORTAL__PORT=8888
```

Compose picks these up automatically; for single containers add extra `-e` arguments or mount a custom env file with `--env-file`.

### Keep artifacts and configs outside the container

- The executor writes logs, screenshots, and downloads to `/app/executor_artifacts`. Map it to a host directory by replacing the
  named volume with a bind mount (for example, `-v $(pwd)/artifacts:/app/executor_artifacts`).
- Bind mount a directory with reusable configs or credentials (for example, `-v $(pwd)/configs:/configs`) and reference them from
your YAML files.

---

Need deeper customization? Browse the source under `src/remote_browser_tool` to plug in different LLM providers, browser backends,
or notification channels. The Docker image already contains Playwright with Chromium, so any custom code you add can reuse the same
base image.
