"""Stateless Copilot API. Java owns identity, authorization and persistence."""
import hmac
import os
from flask import Flask, jsonify, request
from dotenv import load_dotenv

load_dotenv()
from ai_core.integration import analyze, validate_payload

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 512 * 1024


@app.get('/health')
def health():
    return jsonify(status='ok', service='clyvo-copilot', version='4.0.0')


@app.post('/v1/analyze')
def analysis():
    secret = os.getenv('COPILOT_API_TOKEN', '')
    if not secret:
        return jsonify(error='service_not_configured'), 503
    if not hmac.compare_digest(request.headers.get('Authorization', ''), 'Bearer ' + secret):
        return jsonify(error='unauthorized'), 401
    payload = request.get_json(silent=True)
    try:
        validate_payload(payload)
    except (ValueError, TypeError) as exc:
        return jsonify(error='invalid_payload', detail=str(exc)), 400
    try:
        return jsonify(analyze(payload))
    except Exception:
        app.logger.exception('Copilot analysis failed')
        return jsonify(error='analysis_unavailable'), 503


if __name__ == '__main__':
    app.run(host='127.0.0.1', port=int(os.getenv('PORT', '5001')), debug=False)
