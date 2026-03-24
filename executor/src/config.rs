use clap::Parser;

#[derive(Parser, Debug)]
#[command(name = "executor", about = "Solana swap executor")]
pub struct Cli {
    #[command(subcommand)]
    pub command: Commands,
}

#[derive(clap::Subcommand, Debug)]
pub enum Commands {
    Swap {
        #[arg(long)]
        from: String,
        #[arg(long)]
        to: String,
        #[arg(long)]
        amount: f64,
        #[arg(long)]
        dex: String,
        #[arg(long)]
        min_out: f64,
        #[arg(long)]
        rpc_url: String,
        #[arg(long)]
        keypair_path: String,
        #[arg(long, default_value_t = false)]
        dry_run: bool,
        #[arg(long, default_value_t = 500000)]
        priority_fee: u64,
    },
    Balance {
        #[arg(long)]
        rpc_url: String,
        #[arg(long)]
        keypair_path: String,
    },
    SignAndSend {
        #[arg(long)]
        tx_base64: String,
        #[arg(long)]
        rpc_url: String,
        #[arg(long)]
        keypair_path: String,
    },
    Pubkey {
        #[arg(long)]
        keypair_path: String,
    },
    /// Scan all DEXes for arbitrage opportunities (Rust-native detection, ~2-5ms).
    Detect {
        #[arg(long, default_value = "SOL")]
        input_token: String,
        #[arg(long, default_value = "USDC")]
        output_token: String,
        #[arg(long, default_value_t = 0.05)]
        amount: f64,
        #[arg(long, default_value_t = 0.1)]
        min_profit_pct: f64,
    },
    /// Run the full Rust-native bot loop (detect + execute, ~2ms latency).
    Run {
        #[arg(long)]
        rpc_url: String,
        #[arg(long)]
        keypair_path: String,
        #[arg(long, default_value_t = 0.05)]
        amount: f64,
        #[arg(long, default_value_t = 0.1)]
        min_profit_pct: f64,
        #[arg(long, default_value_t = 1)]
        poll_interval_sec: u64,
        #[arg(long, default_value_t = false)]
        dry_run: bool,
    },
    /// Send a Jito bundle of base64-encoded transactions (MEV-protected, atomic).
    SendBundle {
        /// Comma-separated base64-encoded transactions
        #[arg(long)]
        transactions: String,
        #[arg(long)]
        rpc_url: String,
        #[arg(long)]
        keypair_path: String,
        /// Jito tip in lamports (default 50000 = 0.00005 SOL)
        #[arg(long, default_value_t = 50000)]
        tip_lamports: u64,
    },
}
