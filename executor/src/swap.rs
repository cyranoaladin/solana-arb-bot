use anyhow::{Context, Result};
use base64::{engine::general_purpose::STANDARD as BASE64, Engine};
use serde_json::{json, Value};
use solana_client::rpc_client::RpcClient;
use solana_client::rpc_config::RpcSendTransactionConfig;
use solana_sdk::commitment_config::CommitmentConfig;
use solana_sdk::signature::read_keypair_file;
use solana_sdk::signer::Signer;
use solana_sdk::transaction::VersionedTransaction;

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

/// Returns the base58-encoded public key for the given keypair file.
pub fn get_pubkey(keypair_path: &str) -> Result<String> {
    let keypair = read_keypair_file(keypair_path)
        .map_err(|e| anyhow::anyhow!("Failed to read keypair: {}", e))?;
    Ok(keypair.pubkey().to_string())
}

/// Sign a base64-encoded VersionedTransaction and send it to the network.
/// Returns the transaction signature as a string.
pub fn sign_and_send_tx(tx_base64: &str, rpc_url: &str, keypair_path: &str) -> Result<Value> {
    let keypair = read_keypair_file(keypair_path)
        .map_err(|e| anyhow::anyhow!("Failed to read keypair: {}", e))?;

    let tx_bytes = BASE64
        .decode(tx_base64)
        .context("Failed to decode base64 transaction")?;

    let mut tx: VersionedTransaction =
        bincode::deserialize(&tx_bytes).context("Failed to deserialize transaction")?;

    // Sign the transaction: replace the first signature (fee payer) with ours
    let message_bytes = tx.message.serialize();
    let signature = keypair.sign_message(&message_bytes);
    if tx.signatures.is_empty() {
        tx.signatures.push(signature);
    } else {
        tx.signatures[0] = signature;
    }

    let client = RpcClient::new_with_commitment(
        rpc_url.to_string(),
        CommitmentConfig::confirmed(),
    );

    let send_config = RpcSendTransactionConfig {
        skip_preflight: false,
        ..Default::default()
    };

    let sig = client
        .send_transaction_with_config(&tx, send_config)
        .context("Failed to send transaction")?;

    Ok(json!({
        "status": "ok",
        "tx_hash": sig.to_string()
    }))
}

/// Parameters for a swap execution (for future refactoring).
#[allow(dead_code)]
pub struct SwapParams<'a> {
    pub from: &'a str,
    pub to: &'a str,
    pub amount: f64,
    pub dex: &'a str,
    pub min_out: f64,
    pub rpc_url: &'a str,
    pub keypair_path: &'a str,
    pub priority_fee: u64,
}

/// Execute a swap via DEX API. Fetches a swap transaction from the DEX,
/// signs it, and sends it to the network.
#[allow(clippy::too_many_arguments)]
pub fn execute_swap(
    from: &str,
    to: &str,
    amount: f64,
    dex: &str,
    min_out: f64,
    rpc_url: &str,
    keypair_path: &str,
    priority_fee: u64,
    slippage_bps: u64,
) -> Result<Value> {
    let keypair = read_keypair_file(keypair_path)
        .map_err(|e| anyhow::anyhow!("Failed to read keypair: {}", e))?;
    let wallet_pubkey = keypair.pubkey().to_string();

    match dex {
        "raydium" => execute_raydium_swap(from, to, amount, min_out, rpc_url, keypair_path, &wallet_pubkey, priority_fee, slippage_bps),
        "orca" => anyhow::bail!(
            "BLOCKED: Orca live execution not supported. Orca is observation-only in this build. \
             Use dex=raydium for execution."
        ),
        _ => anyhow::bail!("Unsupported DEX: {}. Only 'raydium' is supported for live execution.", dex),
    }
}

fn get_mint(token: &str) -> Result<&'static str> {
    match token {
        "SOL" => Ok("So11111111111111111111111111111111111111112"),
        "USDC" => Ok("EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"),
        "USDT" => Ok("Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB"),
        _ => anyhow::bail!("Unknown token: {}", token),
    }
}

fn get_decimals(token: &str) -> Result<u32> {
    match token {
        "SOL" => Ok(9),
        "USDC" => Ok(6),
        "USDT" => Ok(6),
        _ => anyhow::bail!("Unknown token: {}", token),
    }
}

#[allow(clippy::too_many_arguments)]
fn execute_raydium_swap(
    from: &str,
    to: &str,
    amount: f64,
    min_out: f64,
    rpc_url: &str,
    keypair_path: &str,
    wallet_pubkey: &str,
    priority_fee: u64,
    slippage_bps: u64,
) -> Result<Value> {
    let input_mint = get_mint(from)?;
    let output_mint = get_mint(to)?;
    let input_decimals = get_decimals(from)?;
    let output_decimals = get_decimals(to)?;
    let amount_raw = (amount * 10f64.powi(input_decimals as i32)) as u64;

    let http = reqwest::blocking::Client::builder()
        .timeout(std::time::Duration::from_secs(30))
        .build()?;

    // Step 1: Compute swap route via Raydium API
    let compute_url = format!(
        "https://transaction-v1.raydium.io/compute/swap-base-in?inputMint={}&outputMint={}&amount={}&slippageBps={}&txVersion=V0",
        input_mint, output_mint, amount_raw, slippage_bps
    );

    let compute_resp: Value = http
        .get(&compute_url)
        .send()
        .context("Failed to call Raydium compute API")?
        .json()
        .context("Failed to parse Raydium compute response")?;

    if !compute_resp.get("success").and_then(|v| v.as_bool()).unwrap_or(false) {
        let msg = compute_resp
            .get("msg")
            .and_then(|v| v.as_str())
            .unwrap_or("Unknown error");
        anyhow::bail!("Raydium compute failed: {}", msg);
    }

    let compute_data = compute_resp
        .get("data")
        .ok_or_else(|| anyhow::anyhow!("No data in Raydium compute response"))?;

    // Extract output amount from compute response and verify min_out
    let output_amount_raw = compute_data
        .get("outputAmount")
        .and_then(|v| v.as_str().and_then(|s| s.parse::<u64>().ok()).or_else(|| v.as_u64()))
        .unwrap_or(0);
    let output_amount = output_amount_raw as f64 / 10f64.powi(output_decimals as i32);

    if min_out > 0.0 && output_amount < min_out {
        anyhow::bail!(
            "Raydium quote output {:.6} < min_out {:.6} — trade rejected to protect against slippage",
            output_amount, min_out
        );
    }

    // Step 2: Build swap transaction (with priority fee for faster inclusion)
    let tx_body = json!({
        "swapResponse": compute_data,
        "wallet": wallet_pubkey,
        "wrapSol": from == "SOL",
        "unwrapSol": to == "SOL",
        "txVersion": "V0",
        "computeUnitPriceMicroLamports": priority_fee.to_string()
    });

    let tx_resp: Value = http
        .post("https://transaction-v1.raydium.io/transaction/swap-base-in")
        .json(&tx_body)
        .send()
        .context("Failed to call Raydium transaction API")?
        .json()
        .context("Failed to parse Raydium transaction response")?;

    if !tx_resp.get("success").and_then(|v| v.as_bool()).unwrap_or(false) {
        let msg = tx_resp
            .get("msg")
            .and_then(|v| v.as_str())
            .unwrap_or("Unknown error");
        anyhow::bail!("Raydium transaction build failed: {}", msg);
    }

    // The response contains an array of base64-encoded transactions
    let transactions = tx_resp
        .get("data")
        .and_then(|d| d.as_array())
        .ok_or_else(|| anyhow::anyhow!("No transaction data in Raydium response"))?;

    if transactions.is_empty() {
        anyhow::bail!("Raydium returned no transactions");
    }

    // Sign and send each transaction (usually just one for a simple swap)
    let mut last_sig = String::new();
    for tx_val in transactions {
        let tx_b64 = tx_val
            .get("transaction")
            .and_then(|v| v.as_str())
            .ok_or_else(|| anyhow::anyhow!("Missing transaction field in Raydium response"))?;

        let result = sign_and_send_tx(tx_b64, rpc_url, keypair_path)?;
        last_sig = result["tx_hash"].as_str().unwrap_or("").to_string();
    }

    Ok(json!({
        "status": "ok",
        "tx_hash": last_sig,
        "dex": "raydium",
        "from": from,
        "to": to,
        "amount": amount,
        "output_amount": output_amount,
        "min_out": min_out,
        "slippage_bps": slippage_bps,
        "priority_fee": priority_fee
    }))
}

// NOTE: Orca execution is NOT supported. Orca is used for price observation only.
// The execute_swap() function blocks Orca with an explicit error message.
// This is intentional — Orca has no HTTP swap API.

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_get_mint_sol() {
        assert_eq!(get_mint("SOL").unwrap(), "So11111111111111111111111111111111111111112");
    }

    #[test]
    fn test_get_mint_usdc() {
        assert_eq!(get_mint("USDC").unwrap(), "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v");
    }

    #[test]
    fn test_get_mint_usdt() {
        assert_eq!(get_mint("USDT").unwrap(), "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB");
    }

    #[test]
    fn test_get_mint_unknown() {
        assert!(get_mint("DOGE").is_err());
    }

    #[test]
    fn test_get_decimals() {
        assert_eq!(get_decimals("SOL").unwrap(), 9);
        assert_eq!(get_decimals("USDC").unwrap(), 6);
        assert_eq!(get_decimals("USDT").unwrap(), 6);
        assert!(get_decimals("UNKNOWN").is_err());
    }
}
