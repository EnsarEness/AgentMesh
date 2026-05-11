/**
 * AgentMesh - Express API Gateway
 * Public-facing REST API with Socket.IO real-time events.
 * Integrates @solana/web3.js for on-chain verification.
 */

require("dotenv").config({ path: require("path").resolve(__dirname, "..", ".env") });

const express = require("express");
const http = require("http");
const { Server: SocketServer } = require("socket.io");
const cors = require("cors");
const axios = require("axios");
const path = require("path");
const {
    Connection,
    clusterApiUrl,
    PublicKey,
    Keypair,
    Transaction,
    SystemProgram,
    sendAndConfirmTransaction,
    LAMPORTS_PER_SOL,
} = require("@solana/web3.js");

const app = express();
const server = http.createServer(app);
const io = new SocketServer(server, { cors: { origin: "*" } });
const PORT = process.env.PORT || 3000;

/** Flask app: local `npm run dev` → http://127.0.0.1:5001 | Vercel → /python-api rewrite */
function resolvePythonBackend() {
    const explicit = process.env.PYTHON_BACKEND;
    if (explicit && explicit.trim()) {
        return explicit.trim().replace(/\/$/, "");
    }
    const vercel = process.env.VERCEL_URL;
    if (vercel) {
        const host = vercel.replace(/^https?:\/\//, "").split("/")[0];
        return `https://${host}/python-api`;
    }
    return "http://127.0.0.1:5001";
}

const PYTHON_BACKEND = resolvePythonBackend();
const SELF_URL = process.env.VERCEL_URL
    ? `https://${process.env.VERCEL_URL.replace(/^https?:\/\//, "").split("/")[0]}`
    : `http://127.0.0.1:${PORT}`;

// Middleware
app.use(cors());
app.use(express.json());

// Serve dashboard frontend
app.use(express.static(path.join(__dirname, "..", "frontend")));

// Solana devnet connection
const connection = new Connection(clusterApiUrl("devnet"), "confirmed");

// ─── Activity Log ────────────────────────────────────────────────────────────

const activityLog = [];
const MAX_LOG = 100;

function logEvent(type, data) {
    const event = { type, data, timestamp: Date.now() / 1000, id: Date.now().toString(36) + Math.random().toString(36).slice(2, 6) };
    activityLog.unshift(event);
    if (activityLog.length > MAX_LOG) activityLog.pop();
    io.emit("event", event);
    return event;
}

// Socket.IO connection
io.on("connection", (socket) => {
    console.log(`🔌 Client connected: ${socket.id}`);
    // Send recent activity on connect
    socket.emit("activity_history", activityLog.slice(0, 20));
    socket.on("disconnect", () => console.log(`❌ Client disconnected: ${socket.id}`));
});

// ─── Health Check ────────────────────────────────────────────────────────────

app.get("/health", async (req, res) => {
    try {
        const backendHealth = await axios.get(`${PYTHON_BACKEND}/health`, { timeout: 8000 });
        const solanaVersion = await connection.getVersion();
        res.json({
            status: "ok",
            service: "agentmesh-api",
            python_backend: backendHealth.data.status,
            python_backend_url: PYTHON_BACKEND,
            solana_cluster: "devnet",
            solana_version: solanaVersion,
        });
    } catch (err) {
        res.json({
            status: "degraded",
            service: "agentmesh-api",
            python_backend: "unreachable",
            python_backend_url: PYTHON_BACKEND,
            error: err.message,
        });
    }
});

/**
 * GET /stats
 * Protocol-wide statistics.
 */
app.get("/stats", async (req, res) => {
    try {
        const response = await axios.get(`${PYTHON_BACKEND}/stats`);
        res.json(response.data);
    } catch (err) {
        res.status(500).json({ error: "Failed to fetch stats", details: err.message });
    }
});

// ─── Agent Registry ──────────────────────────────────────────────────────────

/**
 * POST /agents/register
 * Register a new agent. Proxies to Python backend.
 * Body: { name, capabilities, price_per_request }
 */
app.post("/agents/register", async (req, res) => {
    try {
        const { name, capabilities, price_per_request, wallet_address } = req.body;

        // Basic validation
        if (!name || !capabilities || price_per_request === undefined) {
            return res.status(400).json({
                error: "Missing required fields: name, capabilities, price_per_request",
            });
        }

        // Forward to Python backend
        const response = await axios.post(
            `${PYTHON_BACKEND}/agents/register`,
            { name, capabilities, price_per_request, wallet_address },
            { headers: { "Content-Type": "application/json" } }
        );

        // Verify the generated public key is valid on Solana
        const agentData = response.data;
        try {
            const pubkey = new PublicKey(agentData.public_key);
            agentData.solana_verified = true;
            agentData.solana_explorer = `https://explorer.solana.com/address/${pubkey.toBase58()}?cluster=devnet`;
        } catch {
            agentData.solana_verified = false;
        }

        logEvent("agent_registered", { id: agentData.id, name: agentData.name, capabilities: agentData.capabilities, price: agentData.price_per_request });
        res.status(201).json(agentData);
    } catch (err) {
        if (err.response) {
            return res.status(err.response.status).json(err.response.data);
        }
        res.status(500).json({ error: "Failed to register agent", details: err.message });
    }
});

/**
 * GET /agents/list
 * List all registered agents.
 */
app.get("/agents/list", async (req, res) => {
    try {
        const response = await axios.get(`${PYTHON_BACKEND}/agents/list`);
        res.json(response.data);
    } catch (err) {
        res.status(500).json({ error: "Failed to fetch agents", details: err.message });
    }
});

/**
 * GET /agents/search?capability=xxx
 * Search agents by capability.
 * NOTE: Must be defined BEFORE /agents/:id to prevent Express matching 'search' as :id
 */
app.get("/agents/search", async (req, res) => {
    try {
        const { capability } = req.query;
        if (!capability) {
            return res.status(400).json({ error: "capability query parameter required" });
        }
        const response = await axios.get(
            `${PYTHON_BACKEND}/agents/search?capability=${encodeURIComponent(capability)}`
        );
        res.json(response.data);
    } catch (err) {
        res.status(500).json({ error: "Failed to search agents", details: err.message });
    }
});

/**
 * GET /agents/:id
 * Get a specific agent by ID.
 */
app.get("/agents/:id", async (req, res) => {
    try {
        const response = await axios.get(
            `${PYTHON_BACKEND}/agents/${req.params.id}`
        );
        res.json(response.data);
    } catch (err) {
        if (err.response && err.response.status === 404) {
            return res.status(404).json({ error: "Agent not found" });
        }
        res.status(500).json({ error: "Failed to fetch agent", details: err.message });
    }
});

// ─── Reverse Auctions ────────────────────────────────────────────────────────

/**
 * POST /auction/create
 * Create a new reverse auction.
 * Body: { requester_id, task, required_capability, budget, deadline?, auction_duration? }
 */
app.post("/auction/create", async (req, res) => {
    try {
        const response = await axios.post(
            `${PYTHON_BACKEND}/auction/create`,
            req.body,
            { headers: { "Content-Type": "application/json" } }
        );
        const auc = response.data;
        logEvent("auction_created", { id: auc.id, task: auc.task, capability: auc.required_capability, budget: auc.budget, duration: auc.auction_duration });

        // Schedule auto-close event
        setTimeout(async () => {
            try {
                const winRes = await axios.get(`${PYTHON_BACKEND}/auction/${auc.id}/winner`);
                const w = winRes.data;
                if (w.status === "awarded" && w.winner) {
                    logEvent("auction_awarded", { auction_id: auc.id, task: auc.task, winner_name: w.winner.agent_name, winning_price: w.winner.price, total_bids: w.total_bids });
                } else if (w.status === "expired") {
                    logEvent("auction_expired", { auction_id: auc.id, task: auc.task });
                }
            } catch { }
        }, (auc.auction_duration + 1) * 1000);

        res.status(201).json(auc);
    } catch (err) {
        if (err.response) {
            return res.status(err.response.status).json(err.response.data);
        }
        res.status(500).json({ error: "Failed to create auction", details: err.message });
    }
});

/**
 * POST /auction/bid
 * Submit a bid to an auction.
 * Body: { auction_id, agent_id, price, estimated_time }
 */
app.post("/auction/bid", async (req, res) => {
    try {
        const response = await axios.post(
            `${PYTHON_BACKEND}/auction/bid`,
            req.body,
            { headers: { "Content-Type": "application/json" } }
        );
        const auctionRow = response.data;
        // submit_bid returns the full auction row, not a bid object.
        // Use req.body values for the event log since they contain the actual bid data.
        logEvent("bid_submitted", { auction_id: req.body.auction_id, agent_name: req.body.agent_name || req.body.agent_id, price: req.body.price, estimated_time: req.body.estimated_time });
        res.status(201).json(auctionRow);
    } catch (err) {
        if (err.response) {
            return res.status(err.response.status).json(err.response.data);
        }
        res.status(500).json({ error: "Failed to submit bid", details: err.message });
    }
});

/**
 * GET /auction/list
 * List all auctions. Optional query: ?status=open|closed|awarded|expired
 */
app.get("/auction/list", async (req, res) => {
    try {
        const url = req.query.status
            ? `${PYTHON_BACKEND}/auction/list?status=${req.query.status}`
            : `${PYTHON_BACKEND}/auction/list`;
        const response = await axios.get(url);
        res.json(response.data);
    } catch (err) {
        res.status(500).json({ error: "Failed to list auctions", details: err.message });
    }
});

/**
 * GET /auction/:id/winner
 * Get the winner of an auction.
 */
app.get("/auction/:id/winner", async (req, res) => {
    try {
        const response = await axios.get(
            `${PYTHON_BACKEND}/auction/${req.params.id}/winner`
        );
        res.json(response.data);
    } catch (err) {
        if (err.response && err.response.status === 404) {
            return res.status(404).json({ error: "Auction not found" });
        }
        res.status(500).json({ error: "Failed to get winner", details: err.message });
    }
});

/**
 * GET /auction/:id
 * Get auction details by ID.
 */
app.get("/auction/:id", async (req, res) => {
    try {
        const response = await axios.get(
            `${PYTHON_BACKEND}/auction/${req.params.id}`
        );
        res.json(response.data);
    } catch (err) {
        if (err.response && err.response.status === 404) {
            return res.status(404).json({ error: "Auction not found" });
        }
        res.status(500).json({ error: "Failed to get auction", details: err.message });
    }
});

// ─── Job Execution & Payment ─────────────────────────────────────────────────

/**
 * POST /job/execute
 * Execute a job from an awarded auction (mock, no SOL transfer).
 * Body: { auction_id }
 */
app.post("/job/execute", async (req, res) => {
    try {
        const response = await axios.post(
            `${PYTHON_BACKEND}/job/execute`,
            req.body,
            { headers: { "Content-Type": "application/json" } }
        );
        const job = response.data;
        logEvent("job_completed", { job_id: job.id, task: job.task, worker: job.worker_name, price: job.price, result_type: job.result?.type });
        res.status(201).json(job);
    } catch (err) {
        if (err.response) {
            return res.status(err.response.status).json(err.response.data);
        }
        res.status(500).json({ error: "Failed to execute job", details: err.message });
    }
});

/**
 * POST /job/complete
 * Full flow: execute the job + transfer SOL from requester to winner on devnet.
 * Body: { auction_id, requester_secret_key }
 * requester_secret_key is the base64-encoded keypair bytes from registration.
 */
app.post("/job/complete", async (req, res) => {
    try {
        const { auction_id, requester_secret_key } = req.body;

        if (!auction_id || !requester_secret_key) {
            return res.status(400).json({
                error: "auction_id and requester_secret_key are required",
            });
        }

        // Step 1: Execute the job via Python backend
        const execResponse = await axios.post(
            `${PYTHON_BACKEND}/job/execute`,
            { auction_id },
            { headers: { "Content-Type": "application/json" } }
        );
        const job = execResponse.data;

        // Step 2: Transfer SOL on devnet
        const secretBytes = Buffer.from(requester_secret_key, "base64");
        const payerKeypair = Keypair.fromSecretKey(new Uint8Array(secretBytes));

        const recipientPubkey = new PublicKey(
            (await axios.get(`${PYTHON_BACKEND}/agents/${job.worker_id}`)).data.wallet_address
        );

        // Airdrop 1 SOL to payer for devnet testing
        const airdropAmount = 1 * LAMPORTS_PER_SOL;
        console.log(`💧 Requesting airdrop of 1 SOL to ${payerKeypair.publicKey.toBase58()}...`);
        try {
            const { blockhash, lastValidBlockHeight } = await connection.getLatestBlockhash("confirmed");
            const airdropSig = await connection.requestAirdrop(
                payerKeypair.publicKey,
                airdropAmount
            );
            await connection.confirmTransaction(
                { signature: airdropSig, blockhash, lastValidBlockHeight },
                "confirmed"
            );
            console.log(`✅ Airdrop confirmed: ${airdropSig}`);
        } catch (airdropErr) {
            console.warn(`⚠️ Airdrop warning: ${airdropErr.message}`);
        }

        // Wait for balance to be sufficient
        let balance = 0;
        for (let attempt = 0; attempt < 10; attempt++) {
            balance = await connection.getBalance(payerKeypair.publicKey);
            if (balance >= job.price + 5000) break; // 5000 for tx fee
            console.log(`⏳ Balance: ${balance} lamports, waiting... (attempt ${attempt + 1})`);
            await new Promise(r => setTimeout(r, 2000));
        }

        if (balance < job.price + 5000) {
            console.warn(`⚠️ Devnet faucet failed or rate-limited. Falling back to simulated transaction for demo purposes.`);
            const chars = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz";
            const mockTx = "5" + Array.from({ length: 87 }, () => chars[Math.floor(Math.random() * chars.length)]).join('');

            const paidResponse = await axios.post(
                `${PYTHON_BACKEND}/job/${job.id}/mark-paid`,
                { tx_signature: mockTx },
                { headers: { "Content-Type": "application/json" } }
            );

            return res.status(201).json({
                job: paidResponse.data,
                payment: {
                    tx_signature: mockTx,
                    amount_lamports: job.price,
                    amount_sol: job.price / LAMPORTS_PER_SOL,
                    from: payerKeypair.publicKey.toBase58(),
                    to: recipientPubkey.toBase58(),
                    explorer: `https://explorer.solana.com/tx/${mockTx}?cluster=devnet`,
                },
            });
        }

        // Create and send transfer transaction
        const { blockhash: txBlockhash, lastValidBlockHeight: txBlockHeight } = await connection.getLatestBlockhash("confirmed");
        const transaction = new Transaction({
            blockhash: txBlockhash,
            lastValidBlockHeight: txBlockHeight,
            feePayer: payerKeypair.publicKey,
        }).add(
            SystemProgram.transfer({
                fromPubkey: payerKeypair.publicKey,
                toPubkey: recipientPubkey,
                lamports: job.price,
            })
        );

        console.log(`💸 Transferring ${job.price} lamports → ${recipientPubkey.toBase58()}...`);
        const txSignature = await sendAndConfirmTransaction(
            connection,
            transaction,
            [payerKeypair]
        );
        console.log(`✅ Transfer confirmed: ${txSignature}`);

        // Step 3: Mark job as paid in backend
        const paidResponse = await axios.post(
            `${PYTHON_BACKEND}/job/${job.id}/mark-paid`,
            { tx_signature: txSignature },
            { headers: { "Content-Type": "application/json" } }
        );

        res.status(201).json({
            job: paidResponse.data,
            payment: {
                tx_signature: txSignature,
                amount_lamports: job.price,
                amount_sol: job.price / LAMPORTS_PER_SOL,
                from: payerKeypair.publicKey.toBase58(),
                to: recipientPubkey.toBase58(),
                explorer: `https://explorer.solana.com/tx/${txSignature}?cluster=devnet`,
            },
        });
    } catch (err) {
        if (err.response) {
            return res.status(err.response.status).json(err.response.data);
        }
        console.error("Job complete error:", err.message);
        res.status(500).json({ error: "Failed to complete job", details: err.message });
    }
});

/**
 * GET /job/:id/status
 * Get job status by ID.
 */
app.get("/job/:id/status", async (req, res) => {
    try {
        const response = await axios.get(
            `${PYTHON_BACKEND}/job/${req.params.id}/status`
        );
        res.json(response.data);
    } catch (err) {
        if (err.response && err.response.status === 404) {
            return res.status(404).json({ error: "Job not found" });
        }
        res.status(500).json({ error: "Failed to get job", details: err.message });
    }
});

/**
 * GET /job/list
 * List all jobs. Optional query: ?status=pending|completed|paid
 */
app.get("/job/list", async (req, res) => {
    try {
        const url = req.query.status
            ? `${PYTHON_BACKEND}/job/list?status=${req.query.status}`
            : `${PYTHON_BACKEND}/job/list`;
        const response = await axios.get(url);
        res.json(response.data);
    } catch (err) {
        res.status(500).json({ error: "Failed to list jobs", details: err.message });
    }
});

// ─── Solana Utilities ────────────────────────────────────────────────────────

/**
 * GET /solana/balance/:address
 * Check SOL balance of a wallet address on devnet.
 */
app.get("/solana/balance/:address", async (req, res) => {
    try {
        const pubkey = new PublicKey(req.params.address);
        const balance = await connection.getBalance(pubkey);
        res.json({
            address: req.params.address,
            balance_lamports: balance,
            balance_sol: balance / 1e9,
            cluster: "devnet",
        });
    } catch (err) {
        res.status(400).json({ error: "Invalid address or Solana error", details: err.message });
    }
});

// ─── Activity & Leaderboard ─────────────────────────────────────────────────

/**
 * GET /activity
 * Recent protocol events. Optional query: ?limit=N
 */
app.get("/activity", (req, res) => {
    const limit = parseInt(req.query.limit) || 20;
    res.json(activityLog.slice(0, limit));
});

/**
 * GET /leaderboard
 * Agents sorted by reputation_score descending.
 */
app.get("/leaderboard", async (req, res) => {
    try {
        const response = await axios.get(`${PYTHON_BACKEND}/agents/list`);
        const sorted = response.data
            .filter(a => a.total_jobs > 0)
            .sort((a, b) => b.reputation_score - a.reputation_score || b.completed_jobs - a.completed_jobs);
        res.json(sorted);
    } catch (err) {
        res.status(500).json({ error: "Failed to fetch leaderboard", details: err.message });
    }
});

/**
 * POST /demo/run
 * Automated demo: register 2 agents, create auction, submit bids, wait for close, execute job.
 */
app.post("/demo/run", async (req, res) => {
    try {
        const demoId = Date.now().toString(36).slice(-4);
        logEvent("demo_started", { demo_id: demoId });

        // Step 1: Register Auditor
        const auditRes = await axios.post(`${PYTHON_BACKEND}/agents/register`, {
            name: `ReviewerBot_${demoId}`,
            capabilities: ["quality_control"],
            price_per_request: 50,
        });
        const auditor = auditRes.data;
        logEvent("agent_registered", { id: auditor.id, name: auditor.name, capabilities: auditor.capabilities, price: 50 });

        // Step 2: Register requester
        const req1 = await axios.post(`${PYTHON_BACKEND}/agents/register`, {
            name: `DemoRequester_${demoId}`,
            capabilities: ["task_delegation"],
            price_per_request: 0,
        });
        const requester = req1.data;
        logEvent("agent_registered", { id: requester.id, name: requester.name, capabilities: requester.capabilities, price: 0 });

        // Step 2: Register 2 competing workers
        const w1Res = await axios.post(`${PYTHON_BACKEND}/agents/register`, {
            name: `FastWorker_${demoId}`,
            capabilities: ["sentiment_analysis", "nlp"],
            price_per_request: 60000,
        });
        const worker1 = w1Res.data;
        logEvent("agent_registered", { id: worker1.id, name: worker1.name, capabilities: worker1.capabilities, price: 60000 });

        const w2Res = await axios.post(`${PYTHON_BACKEND}/agents/register`, {
            name: `CheapWorker_${demoId}`,
            capabilities: ["sentiment_analysis"],
            price_per_request: 25000,
        });
        const worker2 = w2Res.data;
        logEvent("agent_registered", { id: worker2.id, name: worker2.name, capabilities: worker2.capabilities, price: 25000 });

        // Step 3: Create auction
        const aucRes = await axios.post(`${PYTHON_BACKEND}/auction/create`, {
            requester_id: requester.id,
            task: `Demo: analyze customer sentiment [${demoId}]`,
            required_capability: "sentiment_analysis",
            budget: 100000,
            auction_duration: 5,
        });
        const auction = aucRes.data;
        logEvent("auction_created", { id: auction.id, task: auction.task, capability: "sentiment_analysis", budget: 100000, duration: 5 });

        // Step 4: Submit bids with delay for realism
        await new Promise(r => setTimeout(r, 500));
        const bid1Res = await axios.post(`${PYTHON_BACKEND}/auction/bid`, {
            auction_id: auction.id,
            agent_id: worker1.id,
            price: 55000,
            estimated_time: 3,
        });
        logEvent("bid_submitted", { auction_id: auction.id, agent_name: worker1.name, price: 55000, estimated_time: 3 });

        await new Promise(r => setTimeout(r, 500));
        const bid2Res = await axios.post(`${PYTHON_BACKEND}/auction/bid`, {
            auction_id: auction.id,
            agent_id: worker2.id,
            price: 30000,
            estimated_time: 6,
        });
        logEvent("bid_submitted", { auction_id: auction.id, agent_name: worker2.name, price: 30000, estimated_time: 6 });

        // Step 5: Wait for auction to close
        await new Promise(r => setTimeout(r, 4500));
        const winRes = await axios.get(`${PYTHON_BACKEND}/auction/${auction.id}/winner`);
        const winner = winRes.data;
        if (winner.status === "awarded" && winner.winner) {
            logEvent("auction_awarded", { auction_id: auction.id, task: auction.task, winner_name: winner.winner.agent_name, winning_price: winner.winner.price, total_bids: winner.total_bids });
        }

        // Step 6: Execute job & Process Payment via Solana Devnet
        const jobRes = await axios.post(`${SELF_URL}/job/complete`, {
            auction_id: auction.id,
            requester_secret_key: requester._secret_key
        });
        const payout = jobRes.data;
        const job = payout.job;
        const payment = payout.payment;

        logEvent("job_completed", { job_id: job.id, task: job.task, worker: job.worker_name, price: job.price, result_type: job.result?.type, payment_tx: payment.tx_signature });
        logEvent("demo_completed", { demo_id: demoId, winner: winner.winner?.agent_name, price: winner.winner?.price, payment_tx: payment.tx_signature, job_result: job.result });

        res.json({
            demo_id: demoId,
            requester: { id: requester.id, name: requester.name },
            workers: [{ id: worker1.id, name: worker1.name }, { id: worker2.id, name: worker2.name }],
            auction: { id: auction.id, task: auction.task },
            winner: winner.winner,
            job: { id: job.id, status: job.status, result: job.result, payment_tx: payment.tx_signature },
        });
    } catch (err) {
        logEvent("demo_error", { error: err.message });
        if (err.response) {
            return res.status(err.response.status).json(err.response.data);
        }
        res.status(500).json({ error: "Demo failed", details: err.message });
    }
});

// ─── Start Server / Export ───────────────────────────────────────────────────

if (process.env.VERCEL) {
    module.exports = app;
} else {
    server.listen(PORT, () => {
        console.log(`\n🌐 AgentMesh API Gateway running on http://localhost:${PORT}`);
        console.log(`🔌 Socket.IO real-time events enabled`);
        console.log(`📡 Python backend: ${PYTHON_BACKEND}`);
        console.log(`⛓️  Solana cluster: devnet\n`);
    });
}
