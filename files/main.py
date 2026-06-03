from flask import Flask, request, jsonify
from flask_cors import CORS
import json
import datetime

app = Flask(__name__)
CORS(app)

latest_signal = {
    "price": None,
    "signal": "WARTEN",
    "indicator": "",
    "time": "",
    "source": "Warte auf TradingView..."
}

@app.route('/')
def index():
    return jsonify({"status": "XAUUSD Bot läuft", "version": "1.0"})

@app.route('/webhook', methods=['POST'])
def webhook():
    global latest_signal
    try:
        data = request.get_json(force=True)
        print(f"[WEBHOOK] Empfangen: {data}")

        latest_signal = {
            "price":     data.get("price", "—"),
            "signal":    data.get("signal", "WARTEN").upper(),
            "indicator": data.get("indicator", ""),
            "time":      datetime.datetime.utcnow().strftime("%H:%M:%S UTC"),
            "source":    "TradingView"
        }
        return jsonify({"status": "ok", "received": latest_signal}), 200
    except Exception as e:
        print(f"[FEHLER] {e}")
        return jsonify({"status": "error", "message": str(e)}), 400

@app.route('/signal')
def get_signal():
    return jsonify(latest_signal)

@app.route('/health')
def health():
    return jsonify({"status": "healthy", "time": datetime.datetime.utcnow().isoformat()})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080)
