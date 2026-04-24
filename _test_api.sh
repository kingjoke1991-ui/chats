#!/bin/bash
BASE=https://chat.202574.xyz

echo "=== 1. Health ==="
curl -s $BASE/health/live
echo ""
curl -s $BASE/health/ready
echo ""

echo "=== 2. Login ==="
source /home/ubuntu/chat-oracle/.env 2>/dev/null
LOGIN=$(curl -s -X POST $BASE/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d "{\"email\":\"$ADMIN_BOOTSTRAP_EMAIL\",\"password\":\"$ADMIN_BOOTSTRAP_PASSWORD\"}")
TOKEN=$(echo "$LOGIN" | python3 -c 'import sys,json; print(json.load(sys.stdin)["tokens"]["access_token"])' 2>/dev/null)
if [ -z "$TOKEN" ]; then
  echo "Login failed: $LOGIN"
  exit 1
fi
echo "Token OK: ${TOKEN:0:30}..."

echo "=== 3. /me ==="
ME=$(curl -s $BASE/v1/users/me -H "Authorization: Bearer $TOKEN")
echo "$ME" | python3 -c 'import sys,json; d=json.load(sys.stdin); print(f"User: {d[\"user\"][\"email\"]} admin={d[\"user\"][\"is_admin\"]}")' 2>/dev/null

echo "=== 4. Chat round 1 ==="
CHAT1=$(curl -s --max-time 120 -X POST $BASE/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"messages":[{"role":"user","content":"Hello! My name is TestUser. What is 2+3? Answer briefly."}]}')

CONV_ID=$(echo "$CHAT1" | python3 -c 'import sys,json; d=json.load(sys.stdin); print(d.get("conversation_id",""))' 2>/dev/null)
REPLY1=$(echo "$CHAT1" | python3 -c 'import sys,json; d=json.load(sys.stdin); print(d["choices"][0]["message"]["content"][:200])' 2>/dev/null)

if [ -z "$CONV_ID" ]; then
  echo "Chat1 FAILED: $(echo "$CHAT1" | head -c 500)"
else
  echo "Conv: $CONV_ID"
  echo "Reply1: $REPLY1"
fi

echo "=== 5. Chat round 2 (context test) ==="
if [ -n "$CONV_ID" ]; then
  CHAT2=$(curl -s --max-time 120 -X POST $BASE/v1/chat/completions \
    -H 'Content-Type: application/json' \
    -H "Authorization: Bearer $TOKEN" \
    -d "{\"conversation_id\":\"$CONV_ID\",\"messages\":[{\"role\":\"user\",\"content\":\"What is my name? You should know from our conversation.\"}]}")
  REPLY2=$(echo "$CHAT2" | python3 -c 'import sys,json; d=json.load(sys.stdin); print(d["choices"][0]["message"]["content"][:300])' 2>/dev/null)
  if [ -z "$REPLY2" ]; then
    echo "Chat2 FAILED: $(echo "$CHAT2" | head -c 500)"
  else
    echo "Reply2: $REPLY2"
  fi
else
  echo "Skipped"
fi

echo "=== 6. Conversations ==="
CONVS=$(curl -s $BASE/v1/conversations -H "Authorization: Bearer $TOKEN")
echo "$CONVS" | python3 -c 'import sys,json; d=json.load(sys.stdin); print(f"Total: {d[\"total\"]}"); [print(f"  - {c[\"title\"][:50] if c[\"title\"] else \"(no title)\"} [{c[\"message_count\"]} msgs]") for c in d["items"][:3]]' 2>/dev/null

echo "=== DONE ==="
