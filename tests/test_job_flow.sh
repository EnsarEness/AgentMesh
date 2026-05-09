#!/bin/bash
# AgentMesh Phase 3 - Full Execution & Payment Flow Test
set -e

API="http://localhost:3000"

echo "═══════════════════════════════════════════════════"
echo "  STEP 1: Register fresh agents for this test"
echo "═══════════════════════════════════════════════════"
# Register requester agent
REQUESTER=$(curl -s -X POST $API/agents/register \
  -H "Content-Type: application/json" \
  -d '{"name":"RequesterBot_P3","capabilities":["task_delegation"],"price_per_request":0}')
REQUESTER_ID=$(echo $REQUESTER | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")
REQUESTER_SECRET=$(echo $REQUESTER | python3 -c "import sys,json; print(json.load(sys.stdin)['_secret_key'])")
echo "Requester: $REQUESTER_ID"

# Register worker agent
WORKER=$(curl -s -X POST $API/agents/register \
  -H "Content-Type: application/json" \
  -d '{"name":"WorkerBot_P3","capabilities":["sentiment_analysis","data_processing"],"price_per_request":40000}')
WORKER_ID=$(echo $WORKER | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")
echo "Worker: $WORKER_ID"
echo ""

echo "═══════════════════════════════════════════════════"
echo "  STEP 2: Create auction"
echo "═══════════════════════════════════════════════════"
AUCTION=$(curl -s -X POST $API/auction/create \
  -H "Content-Type: application/json" \
  -d "{\"requester_id\":\"$REQUESTER_ID\",\"task\":\"analyze sentiment\",\"required_capability\":\"sentiment_analysis\",\"budget\":100000,\"auction_duration\":5}")
AUCTION_ID=$(echo $AUCTION | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")
echo "Auction: $AUCTION_ID"
echo ""

echo "═══════════════════════════════════════════════════"
echo "  STEP 3: Worker submits bid"
echo "═══════════════════════════════════════════════════"
curl -s -X POST $API/auction/bid \
  -H "Content-Type: application/json" \
  -d "{\"auction_id\":\"$AUCTION_ID\",\"agent_id\":\"$WORKER_ID\",\"price\":35000,\"estimated_time\":5}" | python3 -m json.tool
echo ""

echo "═══════════════════════════════════════════════════"
echo "  STEP 4: Wait for auction to close (5 seconds)..."
echo "═══════════════════════════════════════════════════"
sleep 6

echo "--- Winner ---"
curl -s $API/auction/$AUCTION_ID/winner | python3 -m json.tool
echo ""

echo "═══════════════════════════════════════════════════"
echo "  STEP 5: Complete job (execute + SOL payment)"
echo "═══════════════════════════════════════════════════"
echo "This will airdrop devnet SOL and transfer to winner..."
echo ""
RESULT=$(curl -s --max-time 60 -X POST $API/job/complete \
  -H "Content-Type: application/json" \
  -d "{\"auction_id\":\"$AUCTION_ID\",\"requester_secret_key\":\"$REQUESTER_SECRET\"}")
echo $RESULT | python3 -m json.tool
echo ""

echo "═══════════════════════════════════════════════════"
echo "  STEP 6: Check job status"
echo "═══════════════════════════════════════════════════"
JOB_ID=$(echo $RESULT | python3 -c "import sys,json; print(json.load(sys.stdin)['job']['id'])")
curl -s $API/job/$JOB_ID/status | python3 -m json.tool
echo ""

echo "✅ Phase 3 execution & payment flow test complete!"
