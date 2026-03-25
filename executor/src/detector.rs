//! Rust-native price detection and arbitrage finding.
//! Replaces the Python price_fetcher + arbitrage modules for 10-50x speed improvement.

use anyhow::{Context, Result};
use serde::Serialize;
use serde_json::Value;

/// A price quote from a DEX.
#[derive(Debug, Clone, Serialize)]
pub struct PriceQuote {
    pub dex: String,
    pub input_token: String,
    pub output_token: String,
    pub input_amount: f64,
    pub output_amount: f64,
    pub price: f64,
}

/// A detected arbitrage opportunity.
#[derive(Debug, Clone, Serialize)]
pub struct Opportunity {
    pub pair: String,
    pub buy_dex: String,
    pub sell_dex: String,
    pub buy_price: f64,
    pub sell_price: f64,
    pub amount: f64,
    pub profit_pct: f64,
    pub estimated_profit: f64,
}

const BASE_TX_FEE_SOL: f64 = 0.000005;
const FEES_PER_ARB_SOL: f64 = BASE_TX_FEE_SOL * 2.0;

pub struct TokenInfo {
    pub mint: &'static str,
    pub decimals: u32,
}

pub fn token_info(symbol: &str) -> Option<TokenInfo> {
    match symbol {
        "SOL" => Some(TokenInfo {
            mint: "So11111111111111111111111111111111111111112",
            decimals: 9,
        }),
        "USDC" => Some(TokenInfo {
            mint: "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
            decimals: 6,
        }),
        "USDT" => Some(TokenInfo {
            mint: "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB",
            decimals: 6,
        }),
        _ => None,
    }
}

/// Fetch price from Orca Whirlpool API (uses the `price` field directly).
pub fn fetch_orca_price(
    http: &reqwest::blocking::Client,
    input_token: &str,
    output_token: &str,
    amount: f64,
) -> Result<Option<PriceQuote>> {
    let input = token_info(input_token).context("Unknown input token")?;
    let output = token_info(output_token).context("Unknown output token")?;

    let url = format!(
        "https://api.orca.so/v2/solana/pools?tokenA={}&tokenB={}",
        input.mint, output.mint
    );

    let resp: Value = http.get(&url).send()?.json()?;
    let empty = vec![];
    let pools = resp
        .get("data")
        .and_then(|d| d.as_array())
        .unwrap_or(&empty);

    // Find matching pool (exact mint match)
    for pool in pools {
        let mint_a = pool.get("tokenMintA").and_then(|v| v.as_str()).unwrap_or("");
        let mint_b = pool.get("tokenMintB").and_then(|v| v.as_str()).unwrap_or("");
        let price_str = pool.get("price").and_then(|v| v.as_str()).unwrap_or("0");
        let price: f64 = price_str.parse().unwrap_or(0.0);
        if price <= 0.0 {
            continue;
        }

        let output_amount = if mint_a == input.mint && mint_b == output.mint {
            amount * price
        } else if mint_a == output.mint && mint_b == input.mint {
            amount / price
        } else {
            continue;
        };

        return Ok(Some(PriceQuote {
            dex: "orca".into(),
            input_token: input_token.into(),
            output_token: output_token.into(),
            input_amount: amount,
            output_amount,
            price: output_amount / amount,
        }));
    }

    Ok(None)
}

/// Fetch price from Raydium compute/swap API.
pub fn fetch_raydium_price(
    http: &reqwest::blocking::Client,
    input_token: &str,
    output_token: &str,
    amount: f64,
) -> Result<Option<PriceQuote>> {
    let input = token_info(input_token).context("Unknown input token")?;
    let output = token_info(output_token).context("Unknown output token")?;
    let amount_raw = (amount * 10f64.powi(input.decimals as i32)) as u64;

    let url = format!(
        "https://transaction-v1.raydium.io/compute/swap-base-in?inputMint={}&outputMint={}&amount={}&slippageBps=50&txVersion=V0",
        input.mint, output.mint, amount_raw
    );

    let resp: Value = http.get(&url).send()?.json()?;

    if !resp
        .get("success")
        .and_then(|v| v.as_bool())
        .unwrap_or(false)
    {
        return Ok(None);
    }

    // Try parsing outputAmount as string first, then as number
    let output_amount = if let Some(s) = resp.get("data").and_then(|d| d.get("outputAmount")) {
        if let Some(s_str) = s.as_str() {
            s_str.parse::<f64>().unwrap_or(0.0) / 10f64.powi(output.decimals as i32)
        } else if let Some(n) = s.as_u64() {
            n as f64 / 10f64.powi(output.decimals as i32)
        } else if let Some(n) = s.as_f64() {
            n / 10f64.powi(output.decimals as i32)
        } else {
            return Ok(None);
        }
    } else {
        return Ok(None);
    };

    if output_amount <= 0.0 {
        return Ok(None);
    }

    Ok(Some(PriceQuote {
        dex: "raydium".into(),
        input_token: input_token.into(),
        output_token: output_token.into(),
        input_amount: amount,
        output_amount,
        price: output_amount / amount,
    }))
}

/// Fetch prices from all DEXes for a given pair.
pub fn fetch_all_prices(
    http: &reqwest::blocking::Client,
    input_token: &str,
    output_token: &str,
    amount: f64,
) -> Vec<PriceQuote> {
    let mut quotes = Vec::new();

    match fetch_orca_price(http, input_token, output_token, amount) {
        Ok(Some(q)) => quotes.push(q),
        Ok(None) => {}
        Err(e) => eprintln!("Orca error: {}", e),
    }

    match fetch_raydium_price(http, input_token, output_token, amount) {
        Ok(Some(q)) => quotes.push(q),
        Ok(None) => {}
        Err(e) => eprintln!("Raydium error: {}", e),
    }

    quotes
}

/// Find arbitrage opportunities from a list of quotes.
pub fn find_opportunities(
    quotes: &[PriceQuote],
    min_profit_pct: f64,
    priority_fee_sol: f64,
) -> Vec<Opportunity> {
    if quotes.len() < 2 {
        return vec![];
    }

    let total_fee = FEES_PER_ARB_SOL + priority_fee_sol;
    let mut opportunities = Vec::new();

    for buy in quotes {
        for sell in quotes {
            if std::ptr::eq(buy, sell) {
                continue;
            }
            if sell.output_amount <= buy.output_amount {
                continue;
            }

            let spread = sell.output_amount - buy.output_amount;

            let fee_in_output = if buy.input_token == "SOL" && buy.input_amount > 0.0 {
                total_fee * (buy.output_amount / buy.input_amount)
            } else {
                0.0
            };

            let net_profit = spread - fee_in_output;
            if net_profit <= 0.0 {
                continue;
            }

            let profit_pct = (net_profit / buy.output_amount) * 100.0;
            if profit_pct < min_profit_pct {
                continue;
            }

            opportunities.push(Opportunity {
                pair: format!("{}/{}", buy.input_token, buy.output_token),
                buy_dex: buy.dex.clone(),
                sell_dex: sell.dex.clone(),
                buy_price: buy.output_amount,
                sell_price: sell.output_amount,
                amount: buy.input_amount,
                profit_pct,
                estimated_profit: net_profit,
            });
        }
    }

    opportunities.sort_by(|a, b| b.profit_pct.partial_cmp(&a.profit_pct).unwrap());
    opportunities
}

#[cfg(test)]
mod tests {
    use super::*;

    fn make_quote(dex: &str, price: f64) -> PriceQuote {
        PriceQuote {
            dex: dex.to_string(),
            input_token: "SOL".to_string(),
            output_token: "USDC".to_string(),
            input_amount: 0.05,
            output_amount: 0.05 * price,
            price,
        }
    }

    #[test]
    fn test_token_info_sol() {
        let info = token_info("SOL").unwrap();
        assert_eq!(info.decimals, 9);
        assert!(info.mint.starts_with("So1"));
    }

    #[test]
    fn test_token_info_usdc() {
        let info = token_info("USDC").unwrap();
        assert_eq!(info.decimals, 6);
    }

    #[test]
    fn test_token_info_unknown() {
        assert!(token_info("UNKNOWN").is_none());
    }

    #[test]
    fn test_find_opportunities_empty() {
        let quotes: Vec<PriceQuote> = vec![];
        let opps = find_opportunities(&quotes, 0.1, 0.0001);
        assert!(opps.is_empty());
    }

    #[test]
    fn test_find_opportunities_single_quote() {
        let quotes = vec![make_quote("orca", 90.0)];
        let opps = find_opportunities(&quotes, 0.1, 0.0001);
        assert!(opps.is_empty());
    }

    #[test]
    fn test_find_opportunities_no_spread() {
        let quotes = vec![make_quote("orca", 90.0), make_quote("raydium", 90.0)];
        let opps = find_opportunities(&quotes, 0.1, 0.0001);
        assert!(opps.is_empty());
    }

    #[test]
    fn test_find_opportunities_profitable() {
        let quotes = vec![make_quote("orca", 90.0), make_quote("raydium", 92.0)];
        let opps = find_opportunities(&quotes, 0.1, 0.0001);
        assert!(!opps.is_empty());
        assert!(opps[0].profit_pct > 0.0);
        assert_eq!(opps[0].pair, "SOL/USDC");
    }

    #[test]
    fn test_find_opportunities_sorted_by_profit() {
        let quotes = vec![
            make_quote("orca", 90.0),
            make_quote("raydium", 91.0),
            make_quote("meteora", 93.0),
        ];
        let opps = find_opportunities(&quotes, 0.1, 0.0001);
        if opps.len() >= 2 {
            assert!(opps[0].profit_pct >= opps[1].profit_pct);
        }
    }

    #[test]
    fn test_find_opportunities_fees_filter() {
        // Tiny spread that should be eaten by fees
        let quotes = vec![make_quote("orca", 90.0), make_quote("raydium", 90.001)];
        let opps = find_opportunities(&quotes, 0.1, 0.0001);
        assert!(opps.is_empty()); // spread too small after fees
    }

    #[test]
    fn test_quote_serialization() {
        let q = make_quote("orca", 90.0);
        let json = serde_json::to_string(&q).unwrap();
        assert!(json.contains("orca"));
        assert!(json.contains("SOL"));
    }

    #[test]
    fn test_opportunity_serialization() {
        let opp = Opportunity {
            pair: "SOL/USDC".to_string(),
            buy_dex: "orca".to_string(),
            sell_dex: "raydium".to_string(),
            buy_price: 4.5,
            sell_price: 4.6,
            amount: 0.05,
            profit_pct: 2.2,
            estimated_profit: 0.1,
        };
        let json = serde_json::to_string(&opp).unwrap();
        assert!(json.contains("SOL/USDC"));
        assert!(json.contains("2.2"));
    }
}
