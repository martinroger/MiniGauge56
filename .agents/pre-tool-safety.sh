#!/usr/bin/env bash
# Antigravity PreToolUse hook: Safety gate for run_command

set -e

python3 -c '
import sys, json, re

try:
    data = json.load(sys.stdin)
    cmd = data.get("toolCall", {}).get("args", {}).get("CommandLine", "")
    
    # Check for lethal system deletion
    if re.search(r"rm\s+(-[rfRF]+\s+)?(/|~|\$HOME)", cmd):
        print(json.dumps({"decision": "deny", "reason": "Destructive root/home directory deletion command blocked by safety-gate hook."}))
        sys.exit(0)
        
    # Check for force push or hard reset requiring explicit confirmation
    if re.search(r"git\s+(push\s+.*--force|push\s+.*-f|reset\s+--hard)", cmd):
        print(json.dumps({"decision": "ask", "reason": "Destructive git command detected. Explicit confirmation required."}))
        sys.exit(0)

    # Allow normal operations
    print(json.dumps({"decision": "allow"}))
except Exception as e:
    # Fail-safe allow if payload parsing fails
    print(json.dumps({"decision": "allow"}))
'
