#!/bin/bash
echo "=== openclaw model config ==="
grep -E "(gemma|llama|model|url|port|host|base_url|api_key|endpoint)" /home/ubuntu/.openclaw/openclaw.json 2>/dev/null | head -30

echo "=== hermes model config ==="
grep -E "(gemma|llama|model|url|port|host|base_url|api_key|endpoint)" /home/ubuntu/bin/hermes-local.sh 2>/dev/null | head -20

echo "=== hermes yaml ==="
find /home/ubuntu/.hermes -name "*.yaml" -o -name "*.yml" -o -name "*.json" 2>/dev/null | head -10
for f in $(find /home/ubuntu/.hermes -name "*.yaml" -o -name "*.yml" 2>/dev/null | head -3); do
  echo "--- $f ---"
  grep -E "(gemma|llama|model|url|port|base)" "$f" 2>/dev/null | head -10
done

echo "=== ollama check ==="
which ollama 2>/dev/null && ollama list 2>/dev/null | head -10
curl -s http://localhost:11434/api/tags 2>/dev/null | head -c 500

echo ""
echo "=== listening ports with model services ==="
ss -tlnp 2>/dev/null | grep -v chat-oracle | grep -E "(8080|11434|5000|8001|3000|19999)"

echo "=== openai compat check on common ports ==="
for port in 11434 8080 19999; do
  echo "port $port:"
  curl -s --connect-timeout 2 http://127.0.0.1:$port/v1/models 2>/dev/null | head -c 300
  echo ""
done
echo "=== DONE ==="
