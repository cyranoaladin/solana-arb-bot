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
    },
    Balance {
        #[arg(long)]
        rpc_url: String,
        #[arg(long)]
        keypair_path: String,
    },
}
