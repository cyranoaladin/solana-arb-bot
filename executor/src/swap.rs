use anyhow::Result;
use serde_json::{json, Value};
use solana_client::rpc_client::RpcClient;
use solana_sdk::signature::read_keypair_file;
use solana_sdk::signer::Signer;

/// Reads the keypair from file, connects to the given RPC URL,
/// and returns the SOL balance in SOL (not lamports).
pub fn get_balance(rpc_url: &str, keypair_path: &str) -> Result<f64> {
    let keypair = read_keypair_file(keypair_path)
        .map_err(|e| anyhow::anyhow!("Failed to read keypair: {}", e))?;
    let client = RpcClient::new(rpc_url.to_string());
    let pubkey = keypair.pubkey();
    let lamports = client.get_balance(&pubkey)?;
    let sol = lamports as f64 / 1_000_000_000.0;
    Ok(sol)
}

/// Placeholder swap execution. Returns a JSON object with status "ok"
/// and a placeholder tx_hash. Real implementation will come later.
pub fn execute_swap(
    from: &str,
    to: &str,
    amount: f64,
    dex: &str,
    min_out: f64,
    _rpc_url: &str,
    _keypair_path: &str,
) -> Result<Value> {
    Ok(json!({
        "status": "ok",
        "tx_hash": "PLACEHOLDER_TX_HASH",
        "from": from,
        "to": to,
        "amount": amount,
        "dex": dex,
        "min_out": min_out
    }))
}
