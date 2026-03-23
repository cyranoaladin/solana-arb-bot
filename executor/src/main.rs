mod config;
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
                swap::execute_swap(&from, &to, amount, &dex, min_out, &rpc_url, &keypair_path)
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
