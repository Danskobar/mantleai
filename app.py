import gradio as gr
import json
import os
import threading
import time
import requests
from groq import Groq
from web3 import Web3
from dotenv import load_dotenv
from datetime import datetime

load_dotenv()

# Connect to Mantle Sepolia
w3 = Web3(Web3.HTTPProvider(os.getenv("RPC_URL", "https://rpc.sepolia.mantle.xyz")))
groq_client = Groq(api_key=os.getenv("GROQ_API_KEY"))
WALLET = os.getenv("WALLET_ADDRESS")

# State
price_history = []
ai_decisions = []
human_decisions = []
agent_running = False
ai_score = 0
human_score = 0

def get_mnt_price():
    try:
        response = requests.get(
            "https://api.coingecko.com/api/v3/simple/price",
            params={"ids": "mantle", "vs_currencies": "usd"},
            timeout=10
        )
        price = response.json().get("mantle", {}).get("usd")
        if price:
            return price
    except:
        pass
    try:
        response = requests.get(
            "https://api.coingecko.com/api/v3/simple/price",
            params={"ids": "ethereum", "vs_currencies": "usd"},
            timeout=10
        )
        return response.json()["ethereum"]["usd"]
    except:
        return None

def get_wallet_balance():
    try:
        balance_wei = w3.eth.get_balance(WALLET)
        return float(w3.from_wei(balance_wei, "ether"))
    except:
        return 0.0

def ai_make_decision(price, history):
    if len(history) < 3:
        return None
    
    history_str = ", ".join([f"${p}" for p in history[-15:]])
    
    # Calculate basic indicators
    if len(history) >= 5:
        recent_avg = sum(history[-5:]) / 5
        older_avg = sum(history[-10:-5]) / 5 if len(history) >= 10 else recent_avg
        trend = "up" if recent_avg > older_avg else "down" if recent_avg < older_avg else "flat"
        pct_change = ((history[-1] - history[-5]) / history[-5]) * 100
    else:
        trend = "unknown"
        pct_change = 0

    prompt = f"""You are MantleAI, an elite AI trading agent competing against humans on Mantle Network.

Current price: ${price}
Price history (last 15): {history_str}
5-period trend: {trend}
Recent price change: {pct_change:.2f}%

You are in a HUMAN vs AI competition. Make the best possible trading decision.

Analyze:
1. Short-term momentum (last 3 prices)
2. Medium-term trend (last 10 prices)
3. Price acceleration or deceleration

Respond ONLY in this exact JSON:
{{
    "action": "BUY" or "SELL" or "HOLD",
    "confidence": "low" or "medium" or "high",
    "reasoning": "sharp 1-2 sentence analysis",
    "price_target": "brief price target or range",
    "risk": "low" or "medium" or "high"
}}"""

    response = groq_client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=250
    )
    
    try:
        text = response.choices[0].message.content
        # Clean JSON
        start = text.find("{")
        end = text.rfind("}") + 1
        return json.loads(text[start:end])
    except:
        return {"action": "HOLD", "confidence": "low", "reasoning": "Error parsing", "price_target": "N/A", "risk": "low"}

def calculate_score(decisions, price_history):
    score = 0
    for d in decisions:
        idx = d.get("price_index", -1)
        if idx >= 0 and idx + 1 < len(price_history):
            current = price_history[idx]
            next_price = price_history[idx + 1]
            change = next_price - current
            if d["action"] == "BUY" and change > 0:
                score += 1
            elif d["action"] == "SELL" and change < 0:
                score += 1
            elif d["action"] == "HOLD" and abs(change) < 1:
                score += 1
    return score

def agent_loop():
    global agent_running, price_history, ai_decisions, ai_score
    while agent_running:
        price = get_mnt_price()
        if price:
            price_history.append(price)
            decision = ai_make_decision(price, price_history)
            if decision:
                entry = {
                    "timestamp": datetime.now().strftime("%H:%M:%S"),
                    "price": price,
                    "action": decision["action"],
                    "confidence": decision["confidence"],
                    "reasoning": decision["reasoning"],
                    "price_target": decision.get("price_target", "N/A"),
                    "risk": decision.get("risk", "medium"),
                    "price_index": len(price_history) - 1
                }
                ai_decisions.append(entry)
                ai_score = calculate_score(ai_decisions, price_history)
                
                with open("ai_trades.json", "w") as f:
                    json.dump(ai_decisions, f, indent=2)
        
        time.sleep(30)

def start_agent():
    global agent_running
    agent_running = True
    t = threading.Thread(target=agent_loop, daemon=True)
    t.start()
    return "🤖 MantleAI Agent started! Making decisions every 30 seconds..."

def stop_agent():
    global agent_running
    agent_running = False
    return "⏹ Agent stopped."

def human_vote(action):
    global human_decisions, human_score
    price = get_mnt_price()
    if not price:
        return "Could not fetch price. Try again.", get_scoreboard()
    
    entry = {
        "timestamp": datetime.now().strftime("%H:%M:%S"),
        "price": price,
        "action": action,
        "price_index": len(price_history) - 1
    }
    human_decisions.append(entry)
    human_score = calculate_score(human_decisions, price_history)
    
    with open("human_trades.json", "w") as f:
        json.dump(human_decisions, f, indent=2)
    
    return f"✅ Your {action} decision recorded at ${price}", get_scoreboard()

def get_scoreboard():
    ai_total = len(ai_decisions)
    human_total = len(human_decisions)
    
    ai_win_rate = (ai_score / ai_total * 100) if ai_total > 0 else 0
    human_win_rate = (human_score / human_total * 100) if human_total > 0 else 0
    
    leader = "🤖 AI Leading!" if ai_score > human_score else "🧠 Human Leading!" if human_score > ai_score else "🤝 Tied!"
    
    return f"""## 🏆 Human vs AI Scoreboard

{leader}

| | 🤖 MantleAI | 🧠 Human |
|---|---|---|
| Decisions | {ai_total} | {human_total} |
| Correct | {ai_score} | {human_score} |
| Win Rate | {ai_win_rate:.1f}% | {human_win_rate:.1f}% |
"""

def get_ai_feed():
    if not ai_decisions:
        return "No AI decisions yet. Start the agent!"
    
    feed = "## 🤖 AI Decision Feed\n\n"
    for d in reversed(ai_decisions[-8:]):
        emoji = "🟢" if d["action"] == "BUY" else "🔴" if d["action"] == "SELL" else "🟡"
        risk_emoji = "🔥" if d["risk"] == "high" else "⚡" if d["risk"] == "medium" else "✅"
        feed += f"{emoji} **{d['timestamp']}** | ${d['price']} | **{d['action']}** ({d['confidence']} confidence) {risk_emoji}\n"
        feed += f"_{d['reasoning']}_\n"
        feed += f"Target: {d['price_target']}\n\n"
    return feed

def get_dashboard():
    price = get_mnt_price()
    balance = get_wallet_balance()
    connected = w3.is_connected()
    
    return f"""## ⚡ MantleAI Dashboard

**Network:** Mantle Sepolia {"✅ Connected" if connected else "❌ Disconnected"}
**Wallet:** `{WALLET[:6] if WALLET else 'N/A'}...{WALLET[-4:] if WALLET else 'N/A'}`
**Balance:** {balance:.4f} MNT
**Current Price:** ${price if price else 'Loading...'}
**Agent:** {"🟢 Running" if agent_running else "🔴 Stopped"}
**AI Decisions:** {len(ai_decisions)} | **Human Decisions:** {len(human_decisions)}
"""

def refresh_all():
    return get_dashboard(), get_ai_feed(), get_scoreboard()

css = (
    "body, .gradio-container { background: #0d1117 !important; font-family: 'Inter', sans-serif !important; }"
    "h1, h2, h3 { color: #00d4aa !important; }"
    "label, p, span { color: #c9d1d9 !important; }"
    "button.primary { background: #00d4aa !important; color: #0d1117 !important; border: none !important; border-radius: 8px !important; font-weight: 600 !important; }"
    "button.primary:hover { background: #00b894 !important; }"
    "button.secondary { background: #21262d !important; color: #c9d1d9 !important; border: 1px solid #30363d !important; border-radius: 8px !important; }"
    ".buy-btn { background: #1a7f4b !important; color: white !important; }"
    ".sell-btn { background: #8b1a1a !important; color: white !important; }"
)

with gr.Blocks(title="MantleAI - Human vs AI", css=css) as app:
    gr.Markdown("""
# ⚡ MantleAI
## Human vs AI Trading Challenge on Mantle Network
*Can you beat the AI? Make your predictions and find out.*
""")

    with gr.Row():
        start_btn = gr.Button("▶ Start AI Agent", variant="primary")
        stop_btn = gr.Button("⏹ Stop Agent", variant="secondary")
        refresh_btn = gr.Button("🔄 Refresh", variant="secondary")

    agent_status = gr.Markdown("Agent is stopped.")

    with gr.Row():
        with gr.Column(scale=2):
            dashboard_md = gr.Markdown(get_dashboard())
            ai_feed_md = gr.Markdown(get_ai_feed())

        with gr.Column(scale=1):
            gr.Markdown("## 🧠 Your Turn — Beat the AI!")
            gr.Markdown("*What's your prediction for the next price move?*")
            
            with gr.Row():
                buy_btn = gr.Button("📈 BUY", variant="primary")
                sell_btn = gr.Button("📉 SELL", variant="secondary")
                hold_btn = gr.Button("⏸ HOLD", variant="secondary")
            
            human_status = gr.Markdown("")
            scoreboard_md = gr.Markdown(get_scoreboard())

    gr.Markdown("*MantleAI — Built for the Mantle Turing Test Hackathon 2026 | #MantleAIHackathon*")

    start_btn.click(start_agent, outputs=[agent_status])
    stop_btn.click(stop_agent, outputs=[agent_status])
    refresh_btn.click(refresh_all, outputs=[dashboard_md, ai_feed_md, scoreboard_md])
    
    buy_btn.click(lambda: human_vote("BUY"), outputs=[human_status, scoreboard_md])
    sell_btn.click(lambda: human_vote("SELL"), outputs=[human_status, scoreboard_md])
    hold_btn.click(lambda: human_vote("HOLD"), outputs=[human_status, scoreboard_md])

app.launch(server_name="0.0.0.0", server_port=7860)