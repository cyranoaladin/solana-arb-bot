//! Jito bundle submission via HTTP JSON-RPC API.
//! Sends atomic transaction bundles through Jito's block engine
//! for MEV protection (invisible in the standard mempool).

use anyhow::{Context, Result};
use base64::{engine::general_purpose::STANDARD as BASE64, Engine};
use rand::seq::SliceRandom;
use serde_json::{json, Value};
use solana_client::rpc_client::RpcClient;
use solana_sdk::pubkey::Pubkey;
use solana_sdk::signature::read_keypair_file;
use solana_sdk::signer::Signer;
use solana_sdk::system_instruction;
use solana_sdk::transaction::VersionedTransaction;

const JITO_BUNDLE_URL: &str = "https://mainnet.block-engine.jito.wtf/api/v1/bundles";

/// Canonical Jito tip accounts — pick one at random per bundle.
const TIP_ACCOUNTS: &[&str] = &[
    "96gYZGLnJYVFmbjzopPSU6QiEV5fGqZNyN9nmNhvrZU5",
    "HFqU5x63VTqvQss8hp11i4bVqkfRtQ7NmXwkiNPLYH3s",
    "Cw8CFyM9FkoMi7K7Crf6HNQqf4uEMzpKw6QNghXLvLkY",
    "ADaUMid9yfUytqMBgopwjb2o3J2F9Fd1E1EE5GYGahMJ",
    "DfXygSm4jCyNCybVYYK6DwvWqjKee8pbDmJGcLWNDXjh",
    "ADuUkR4vqLUMWXxW9gh6D6L8pMSawimctcNZ5pGwDcEt",
    "DttWaMuVvTiduZRnguLF7jNxTgiMBZ1hyAumKUiL6d33",
    "3AVi9Tg9Uo68tJfuvoKvqKNWKkC5wPdSSdeBnizKZ6jT",
];

/// Sign multiple base64-encoded transactions and send them as an atomic Jito bundle.
/// A SOL tip is added as a separate transaction appended to the bundle.
pub fn send_bundle(
    tx_base64_list: &[String],
    tip_lamports: u64,
    rpc_url: &str,
    keypair_path: &str,
) -> Result<Value> {
    let keypair = read_keypair_file(keypair_path)
        .map_err(|e| anyhow::anyhow!("Failed to read keypair: {}", e))?;

    let client = RpcClient::new(rpc_url.to_string());
    let recent_blockhash = client
        .get_latest_blockhash()
        .context("Failed to get recent blockhash")?;

    // Sign each transaction
    let mut signed_b58: Vec<String> = Vec::new();
    for tx_b64 in tx_base64_list {
        let tx_bytes = BASE64.decode(tx_b64).context("Failed to decode base64 tx")?;
        let mut tx: VersionedTransaction =
            bincode::deserialize(&tx_bytes).context("Failed to deserialize tx")?;

        let message_bytes = tx.message.serialize();
        let sig = keypair.sign_message(&message_bytes);
        if tx.signatures.is_empty() {
            tx.signatures.push(sig);
        } else {
            tx.signatures[0] = sig;
        }

        let serialized = bincode::serialize(&tx).context("Failed to serialize signed tx")?;
        signed_b58.push(bs58::encode(&serialized).into_string());
    }

    // Build the tip transaction
    let tip_account_str = TIP_ACCOUNTS
        .choose(&mut rand::thread_rng())
        .ok_or_else(|| anyhow::anyhow!("No tip accounts"))?;
    let tip_pubkey: Pubkey = tip_account_str
        .parse()
        .context("Failed to parse tip account pubkey")?;

    let tip_ix = system_instruction::transfer(&keypair.pubkey(), &tip_pubkey, tip_lamports);
    let tip_tx = solana_sdk::transaction::Transaction::new_signed_with_payer(
        &[tip_ix],
        Some(&keypair.pubkey()),
        &[&keypair],
        recent_blockhash,
    );
    let tip_serialized = bincode::serialize(&tip_tx).context("Failed to serialize tip tx")?;
    signed_b58.push(bs58::encode(&tip_serialized).into_string());

    // Send bundle via Jito HTTP API
    let bundle_request = json!({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "sendBundle",
        "params": [signed_b58]
    });

    let http = reqwest::blocking::Client::builder()
        .timeout(std::time::Duration::from_secs(15))
        .build()?;

    let resp: Value = http
        .post(JITO_BUNDLE_URL)
        .json(&bundle_request)
        .send()
        .context("Failed to send Jito bundle")?
        .json()
        .context("Failed to parse Jito response")?;

    if let Some(error) = resp.get("error") {
        anyhow::bail!("Jito bundle error: {}", error);
    }

    let bundle_id = resp
        .get("result")
        .and_then(|v| v.as_str())
        .unwrap_or("unknown")
        .to_string();

    Ok(json!({
        "status": "ok",
        "bundle_id": bundle_id,
        "tip_lamports": tip_lamports,
        "tip_account": tip_account_str,
        "transactions": tx_base64_list.len()
    }))
}

/// Check the status of a previously submitted Jito bundle.
pub fn get_bundle_status(bundle_id: &str) -> Result<Value> {
    let request = json!({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "getBundleStatuses",
        "params": [[bundle_id]]
    });

    let http = reqwest::blocking::Client::builder()
        .timeout(std::time::Duration::from_secs(10))
        .build()?;

    let resp: Value = http
        .post(JITO_BUNDLE_URL)
        .json(&request)
        .send()
        .context("Failed to query Jito bundle status")?
        .json()
        .context("Failed to parse Jito status response")?;

    Ok(resp)
}
