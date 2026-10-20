# Starts the LangGraph API (agent + UI card) and Agent Chat UI, then opens the dashboard.
# Thunderbird must be running with the Thunderbird-MCP add-on installed.
$root = $PSScriptRoot

Start-Process -FilePath "$root\.venv\Scripts\langgraph.exe" `
    -ArgumentList "dev", "--no-browser", "--allow-blocking", "--port", "2024" `
    -WorkingDirectory $root

$env:NEXT_PUBLIC_API_URL = "http://localhost:2024"
$env:NEXT_PUBLIC_ASSISTANT_ID = "unsubscribe_agent"
Start-Process -FilePath "npx.cmd" -ArgumentList "-y", "pnpm@10", "dev" -WorkingDirectory "$root\agent-chat-ui"

Start-Sleep -Seconds 15
Start-Process "http://localhost:3000/?apiUrl=http://localhost:2024&assistantId=unsubscribe_agent"
