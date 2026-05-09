#!/bin/bash
# AgentMesh Phase 2 - Full Auction Flow Test
set -e

API="http://localhost:3000"
SENTIMENT_BOT_ID="47dba4c9-5165-4c6b-b9a5-b5cc4ffba0ea"
CODE_REVIEW_ID="73851c2c-1413-40e7-93fc-97620ab2f4fe"

echo "═══════════════════════════════════════════════════"
echo "  STEP 1: Register a competing sentiment agent"
echo "═══════════════════════════════════════════════════"
CHEAP_BOT=$(curl -s -X POST $API/agents/register \
  -H "Content-Type: application/json" \
  -d '{"name":"CheapSentimentBot","capabilities":["sentiment_analysis"],"price_per_request":30000}')
CHEAP_BOT_ID=$(echo $CHEAP_BOT | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")
echo "Registered CheapSentimentBot: $CHEAP_BOT_ID"
echo ""

echo "═══════════════════════════════════════════════════"
echo "  STEP 2: Create an auction (requester = CodeReviewAgent)"
echo "═══════════════════════════════════════════════════"
AUCTION=$(curl -s -X POST $API/auction/create \
  -H "Content-Type: application/json" \
  -d "{\"requester_id\":\"$CODE_REVIEW_ID\",\"task\":\"analyze sentiment of customer feedback\",\"required_capability\":\"sentiment_analysis\",\"budget\":100000,\"deadline\":30,\"auction_duration\":10}")
echo $AUCTION | python3 -m json.tool
AUCTION_ID=$(echo $AUCTION | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")
echo ""
echo "Auction ID: $AUCTION_ID"
echo ""

echo "═══════════════════════════════════════════════════"
echo "  STEP 3: Submit bids from eligible agents"
echo "═══════════════════════════════════════════════════"
echo "--- SentimentBot bids 45000 lamports ---"
curl -s -X POST $API/auction/bid \
  -H "Content-Type: application/json" \
  -d "{\"auction_id\":\"$AUCTION_ID\",\"agent_id\":\"$SENTIMENT_BOT_ID\",\"price\":45000,\"estimated_time\":5}" | python3 -m json.tool
echo ""

echo "--- CheapSentimentBot bids 25000 lamports ---"
curl -s -X POST $API/auction/bid \
  -H "Content-Type: application/json" \
  -d "{\"auction_id\":\"$AUCTION_ID\",\"agent_id\":\"$CHEAP_BOT_ID\",\"price\":25000,\"estimated_time\":8}" | python3 -m json.tool
echo ""

echo "═══════════════════════════════════════════════════"
echo "  STEP 4: Check auction status (should be open)"
echo "═══════════════════════════════════════════════════"
curl -s $API/auction/$AUCTION_ID | python3 -m json.tool
echo ""

echo "═══════════════════════════════════════════════════"
echo "  STEP 5: Wait for auction to close (10 seconds)..."
echo "═══════════════════════════════════════════════════"
sleep 11
echo ""

echo "═══════════════════════════════════════════════════"
echo "  STEP 6: Get winner (should be CheapSentimentBot)"
echo "═══════════════════════════════════════════════════"
curl -s $API/auction/$AUCTION_ID/winner | python3 -m json.tool
echo ""

echo "═══════════════════════════════════════════════════"
echo "  STEP 7: List all auctions"
echo "═══════════════════════════════════════════════════"
curl -s $API/auction/list | python3 -m json.tool
echo ""

echo "✅ Phase 2 auction flow test complete!"
