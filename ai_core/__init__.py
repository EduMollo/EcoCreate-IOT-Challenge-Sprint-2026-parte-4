"""
CLYVO VET — CLYVO Copilot (núcleo de IA)
Disruptive Architectures: IoT, IoB & Generative IA — Sprint 3
FIAP 2026

Camadas:
    C0  db.py           — persistência SQLite
    C1  features.py     — baseline individual (EWMA) + z-score
    C2  risk_model.py   — IsolationForest + RandomForest (scikit-learn)
    C3  rules.py        — motor de regras clínicas (protocols.yaml)
    C4  recommender.py  — recomendação content-based (services.yaml)
    C5  llm.py + rag.py — IA Generativa (Claude API) + RAG leve
        guardrails.py   — validação da saída generativa
        pipeline.py     — orquestra tudo em um "insight"
"""

__version__ = "3.0.0"
