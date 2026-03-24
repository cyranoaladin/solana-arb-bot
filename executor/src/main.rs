mod config;
mod detector;
mod jito;
mod swap;

use clap::Parser;
use config::{Cli, Commands};
use serde_json::json;

fn main() {
    let cli = Cli::parse();

    let result = match cli.command {
        Commands::Swap {
            from,
            to,
            amount,
            dex,
            min_out,
            rpc_url,
            keypair_path,
            dry_run,
            priority_fee,
        } => {
            if dry_run {
                Ok(json!({
                    "status": "dry_run",
                    "from": from,
                    "to": to,
                    "amount": amount,
                    "dex": dex,
                    "min_out": min_out
                }))
            } else {
                swap::execute_swap(&from, &to, amount, &dex, min_out, &rpc_url, &keypair_path, priority_fee)
            }
        }
        Commands::Balance {
            rpc_url,
            keypair_path,
        } => {
            match swap::get_balance(&rpc_url, &keypair_path) {
                Ok(balance) => Ok(json!({
                    "status": "ok",
                    "balance_sol": balance
                })),
                Err(e) => Err(e),
            }
        }
        Commands::SignAndSend {
            tx_base64,
            rpc_url,
            keypair_path,
        } => swap::sign_and_send_tx(&tx_base64, &rpc_url, &keypair_path),
        Commands::Pubkey { keypair_path } => {
            match swap::get_pubkey(&keypair_path) {
                Ok(pubkey) => Ok(json!({
                    "status": "ok",
                    "pubkey": pubkey
                })),
                Err(e) => Err(e),
            }
        }
        Commands::Detect {
            input_token,
            output_token,
            amount,
            min_profit_pct,
        } => run_detect(&input_token, &output_token, amount, min_profit_pct),
        Commands::Run {
            rpc_url,
            keypair_path,
            amount,
            min_profit_pct,
            poll_interval_sec,
            dry_run,
        } => run_loop(&rpc_url, &keypair_path, amount, min_profit_pct, poll_interval_sec, dry_run),
        Commands::SendBundle {
            transactions,
            rpc_url,
            keypair_path,
            tip_lamports,
        } => {
            let tx_list: Vec<String> = transactions
                .split(',')
                .map(|s| s.trim().to_string())
                .filter(|s| !s.is_empty())
                .collect();
            if tx_list.is_empty() {
                Err(anyhow::anyhow!("No transactions provided"))
            } else {
                jito::send_bundle(&tx_list, tip_lamports, &rpc_url, &keypair_path)
            }
        }
    };

    match result {
        Ok(value) => println!("{}", serde_json::to_string_pretty(&value).unwrap()),
        Err(e) => {
            let err_json = json!({
                "status": "error",
                "message": format!("{}", e)
            });
            eprintln!("{}", serde_json::to_string_pretty(&err_json).unwrap());
            std::process::exit(1);
        }
    }
}

/// One-shot scan: fetch prices from all DEXes and find arb opportunities.
fn run_detect(
    input_token: &str,
    output_token: &str,
    amount: f64,
    min_profit_pct: f64,
) -> anyhow::Result<serde_json::Value> {
    let http = reqwest::blocking::Client::builder()
        .timeout(std::time::Duration::from_secs(10))
        .build()?;

    let start = std::time::Instant::now();
    let quotes = detector::fetch_all_prices(&http, input_token, output_token, amount);
    let fetch_ms = start.elapsed().as_millis();

    let opps = detector::find_opportunities(&quotes, min_profit_pct, 0.0001);
    let total_ms = start.elapsed().as_millis();

    Ok(json!({
        "status": "ok",
        "quotes": quotes,
        "opportunities": opps,
        "timing": {
            "fetch_ms": fetch_ms,
            "total_ms": total_ms,
        }
    }))
}

/// Full bot loop in Rust: detect + execute continuously.
fn run_loop(
    rpc_url: &str,
    keypair_path: &str,
    amount: f64,
    min_profit_pct: f64,
    poll_interval_sec: u64,
    dry_run: bool,
) -> anyhow::Result<serde_json::Value> {
    let http = reqwest::blocking::Client::builder()
        .timeout(std::time::Duration::from_secs(10))
        .build()?;

    let pairs = [("SOL", "USDC"), ("SOL", "USDT")];
    let mut total_trades = 0u64;
    let mut total_profit = 0.0f64;

    eprintln!("Rust bot started — dry_run={}, poll={}s, amount={}", dry_run, poll_interval_sec, amount);

    loop {
        for (input_token, output_token) in &pairs {
            let start = std::time::Instant::now();
            let quotes = detector::fetch_all_prices(&http, input_token, output_token, amount);
            let opps = detector::find_opportunities(&quotes, min_profit_pct, 0.0001);
            let detect_ms = start.elapsed().as_millis();

            if !opps.is_empty() {
                for opp in &opps {
                    eprintln!(
                        "[{:.0}ms] {} buy@{}({:.4}) sell@{}({:.4}) profit={:.4}%",
                        detect_ms, opp.pair, opp.buy_dex, opp.buy_price,
                        opp.sell_dex, opp.sell_price, opp.profit_pct,
                    );

                    if !dry_run {
                        // Execute via Raydium swap API
                        match swap::execute_swap(
                            input_token, output_token, amount, "raydium",
                            opp.sell_price * 0.995, rpc_url, keypair_path, 500_000,
                        ) {
                            Ok(result) => {
                                let tx = result.get("tx_hash").and_then(|v| v.as_str()).unwrap_or("n/a");
                                eprintln!("  Leg 1 OK: {}", tx);
                            }
                            Err(e) => eprintln!("  Leg 1 FAIL: {}", e),
                        }
                        match swap::execute_swap(
                            output_token, input_token, opp.sell_price, "raydium",
                            amount * 0.995, rpc_url, keypair_path, 500_000,
                        ) {
                            Ok(result) => {
                                let tx = result.get("tx_hash").and_then(|v| v.as_str()).unwrap_or("n/a");
                                eprintln!("  Leg 2 OK: {}", tx);
                            }
                            Err(e) => eprintln!("  Leg 2 FAIL: {}", e),
                        }
                    }

                    total_trades += 1;
                    total_profit += opp.estimated_profit;
                }
            }
        }

        std::thread::sleep(std::time::Duration::from_secs(poll_interval_sec));
    }
}
