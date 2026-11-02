"""
RAG leve — recuperação sobre a base de conhecimento da clínica (knowledge/*.md)

TF-IDF + similaridade de cosseno. Sem banco vetorial: a base é pequena,
local e versionada no repositório. Cada documento é dividido em trechos
por título "## ", e os k trechos mais relevantes entram no prompt do LLM
como contexto ANCORADO — o modelo redige sobre o que a clínica documentou,
não sobre o que ele "acha".
"""

import glob
import os
import re

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import linear_kernel

KNOWLEDGE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "knowledge")


class KnowledgeBase:
    def __init__(self, knowledge_dir: str = KNOWLEDGE_DIR):
        self.dir = knowledge_dir
        self.chunks: list[dict] = []
        self.vectorizer = None
        self.matrix = None
        self._load()

    def _load(self):
        for path in sorted(glob.glob(os.path.join(self.dir, "*.md"))):
            with open(path, encoding="utf-8") as f:
                text = f.read()
            source = os.path.basename(path)
            parts = re.split(r"(?m)^## +", text)
            for part in parts:
                part = part.strip()
                if not part:
                    continue
                lines = part.split("\n", 1)
                heading = lines[0].strip("# ").strip()
                body = lines[1].strip() if len(lines) > 1 else ""
                if len(body) < 20:
                    continue
                self.chunks.append({"source": source, "heading": heading, "text": body})
        if self.chunks:
            self.vectorizer = TfidfVectorizer(strip_accents="unicode", lowercase=True,
                                              ngram_range=(1, 2), sublinear_tf=True, min_df=1)
            self.matrix = self.vectorizer.fit_transform(f"{c['heading']}\n{c['text']}" for c in self.chunks)

    def search(self, query: str, k: int = 3, min_score: float = 0.05) -> list[dict]:
        if not self.chunks or not query.strip():
            return []
        q = self.vectorizer.transform([query])
        sims = linear_kernel(q, self.matrix).ravel()
        order = sims.argsort()[::-1][:k]
        return [
            {**self.chunks[i], "score": round(float(sims[i]), 3)}
            for i in order if sims[i] >= min_score
        ]

    def __len__(self):
        return len(self.chunks)
