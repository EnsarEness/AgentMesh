const { Connection, clusterApiUrl, PublicKey } = require("@solana/web3.js");
const connection = new Connection(clusterApiUrl("devnet"), "confirmed");

async function run() {
    try {
        const sigs = await connection.getSignaturesForAddress(new PublicKey("11111111111111111111111111111111"), {limit: 5});
        console.log("SIGS:");
        console.dir(sigs);
    } catch(e) {
        console.error("ERROR:");
        console.error(e);
    }
}
run();
