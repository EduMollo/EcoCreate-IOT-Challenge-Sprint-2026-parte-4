"""
CLYVO VET - Pet Detection & Classification System
Disruptive Architectures: IoT, IoB & Generative IA - Sprint 1 → Sprint 3
FIAP 2026

Descrição:
    Script Python para detecção e classificação de pets utilizando
    visão computacional. Identifica a espécie do pet (cão/gato),
    detecta comportamentos e sinais de alerta de saúde.

    Sprint 3: a visão vira SENSOR COMPORTAMENTAL. O deslocamento do
    bounding box entre frames gera um activity_score (0..1) publicado no
    dashboard, que o CLYVO Copilot usa como feature do baseline individual.
"""

import cv2
import numpy as np
import time
import json
import os
import threading
import requests
from datetime import datetime


# ─── Configurações ────────────────────────────────────────────────────────────
CONFIDENCE_THRESHOLD = 0.5
NMS_THRESHOLD = 0.4
INPUT_WIDTH = 416
INPUT_HEIGHT = 416

# Cores para visualização (BGR)
COLORS = {
    "dog":     (0, 200, 80),
    "cat":     (255, 140, 0),
    "alert":   (0, 0, 255),
    "info":    (255, 255, 255),
    "bg":      (20, 20, 20),
    "panel":   (35, 35, 35),
    "accent":  (0, 180, 255),
}

# Classes de animais relevantes no COCO dataset
PET_CLASSES = {
    "dog": 16,
    "cat": 15,
}

# Mapeamento de estado comportamental simulado
BEHAVIOR_STATES = ["Descansando", "Ativo", "Comendo", "Alerta", "Dormindo"]
# Amplitude de movimento simulado por estado (alimenta o ActivityTracker no modo sem YOLO)
MOTION_BY_BEHAVIOR = {"Descansando": 0.15, "Ativo": 1.0, "Comendo": 0.35, "Alerta": 0.7, "Dormindo": 0.05}

# Sprint 3 — publicação do índice de atividade para o CLYVO Copilot
DASHBOARD_ACTIVITY_URL = os.getenv("CLYVO_DASHBOARD_URL", "http://localhost:5000") + "/api/activity"
PET_NAME = os.getenv("CLYVO_PET", "Thor")
ACTIVITY_PUSH_INTERVAL = 2.0   # segundos


# ─── Utilitários ──────────────────────────────────────────────────────────────
def load_yolo_model(weights_path: str, config_path: str):
    """Carrega modelo YOLO para detecção de objetos."""
    if not os.path.exists(weights_path) or not os.path.exists(config_path):
        print("[AVISO] Arquivos YOLO não encontrados. Usando modo de simulação.")
        return None
    net = cv2.dnn.readNet(weights_path, config_path)
    net.setPreferableBackend(cv2.dnn.DNN_BACKEND_OPENCV)
    net.setPreferableTarget(cv2.dnn.DNN_TARGET_CPU)
    return net


def get_output_layers(net):
    """Retorna nomes das camadas de saída do modelo."""
    layer_names = net.getLayerNames()
    return [layer_names[i - 1] for i in net.getUnconnectedOutLayers()]


def draw_rounded_rect(img, pt1, pt2, color, thickness=2, radius=8):
    """Desenha retângulo com bordas arredondadas."""
    x1, y1 = pt1
    x2, y2 = pt2
    cv2.line(img, (x1 + radius, y1), (x2 - radius, y1), color, thickness)
    cv2.line(img, (x1 + radius, y2), (x2 - radius, y2), color, thickness)
    cv2.line(img, (x1, y1 + radius), (x1, y2 - radius), color, thickness)
    cv2.line(img, (x2, y1 + radius), (x2, y2 - radius), color, thickness)
    cv2.ellipse(img, (x1 + radius, y1 + radius), (radius, radius), 180, 0, 90, color, thickness)
    cv2.ellipse(img, (x2 - radius, y1 + radius), (radius, radius), 270, 0, 90, color, thickness)
    cv2.ellipse(img, (x1 + radius, y2 - radius), (radius, radius), 90, 0, 90, color, thickness)
    cv2.ellipse(img, (x2 - radius, y2 - radius), (radius, radius), 0, 0, 90, color, thickness)


def draw_panel(img, x, y, w, h, color=None, alpha=0.6):
    """Desenha painel semi-transparente."""
    color = color or COLORS["panel"]
    overlay = img.copy()
    cv2.rectangle(overlay, (x, y), (x + w, y + h), color, -1)
    cv2.addWeighted(overlay, alpha, img, 1 - alpha, 0, img)


def simulate_vitals(pet_type: str) -> dict:
    """Simula sinais vitais do pet com variação realista."""
    base = {
        "dog": {"temp": 38.5, "hr": 90, "rr": 22},
        "cat": {"temp": 38.8, "hr": 160, "rr": 25},
    }
    b = base.get(pet_type, base["dog"])
    return {
        "temperature": round(b["temp"] + np.random.uniform(-0.3, 0.4), 1),
        "heart_rate":  int(b["hr"] + np.random.randint(-10, 15)),
        "resp_rate":   int(b["rr"] + np.random.randint(-3, 4)),
    }


def assess_health_alert(vitals: dict, pet_type: str) -> tuple[str, tuple]:
    """Avalia sinais vitais e retorna status e cor."""
    thresholds = {
        "dog": {"temp": (37.5, 39.5), "hr": (60, 140), "rr": (10, 35)},
        "cat": {"temp": (37.8, 39.2), "hr": (120, 220), "rr": (16, 40)},
    }
    t = thresholds.get(pet_type, thresholds["dog"])
    alerts = []
    if not (t["temp"][0] <= vitals["temperature"] <= t["temp"][1]):
        alerts.append("Temperatura anormal")
    if not (t["hr"][0] <= vitals["heart_rate"] <= t["hr"][1]):
        alerts.append("FC fora do range")
    if not (t["rr"][0] <= vitals["resp_rate"] <= t["rr"][1]):
        alerts.append("FR fora do range")

    if alerts:
        return f"ALERTA: {', '.join(alerts)}", COLORS["alert"]
    return "Sinais vitais normais", (0, 200, 100)


# ─── Detecção com YOLO ────────────────────────────────────────────────────────
def detect_pets_yolo(frame, net, output_layers, coco_names):
    """Detecta pets no frame usando YOLO."""
    h, w = frame.shape[:2]
    blob = cv2.dnn.blobFromImage(frame, 1 / 255.0, (INPUT_WIDTH, INPUT_HEIGHT),
                                  swapRB=True, crop=False)
    net.setInput(blob)
    outputs = net.forward(output_layers)

    boxes, confidences, class_ids = [], [], []
    for output in outputs:
        for detection in output:
            scores = detection[5:]
            class_id = int(np.argmax(scores))
            confidence = float(scores[class_id])
            if confidence > CONFIDENCE_THRESHOLD and class_id in PET_CLASSES.values():
                cx, cy, bw, bh = (detection[:4] * np.array([w, h, w, h])).astype(int)
                x, y = cx - bw // 2, cy - bh // 2
                boxes.append([x, y, bw, bh])
                confidences.append(confidence)
                class_ids.append(class_id)

    indices = cv2.dnn.NMSBoxes(boxes, confidences, CONFIDENCE_THRESHOLD, NMS_THRESHOLD)
    detections = []
    if len(indices) > 0:
        for i in indices.flatten():
            detections.append({
                "box": boxes[i],
                "confidence": confidences[i],
                "class_id": class_ids[i],
                "label": coco_names[class_ids[i]],
            })
    return detections


# ─── Modo Simulação (sem YOLO) ────────────────────────────────────────────────
class SimulatedDetector:
    """Simula detecções de pets para demonstração quando YOLO não está disponível."""

    def __init__(self):
        self.frame_count = 0
        self.current_pet = "dog"
        self.behavior_idx = 0
        self.switch_interval = 120  # troca de pet a cada N frames

    def detect(self, frame):
        self.frame_count += 1
        if self.frame_count % self.switch_interval == 0:
            self.current_pet = "cat" if self.current_pet == "dog" else "dog"
            self.behavior_idx = (self.behavior_idx + 1) % len(BEHAVIOR_STATES)

        h, w = frame.shape[:2]
        bw, bh = int(w * 0.35), int(h * 0.55)
        # Movimento simulado proporcional ao estado comportamental (alimenta o ActivityTracker)
        amp = MOTION_BY_BEHAVIOR.get(BEHAVIOR_STATES[self.behavior_idx], 0.3)
        x = int(w * 0.32 + w * 0.15 * amp * np.sin(self.frame_count / 12))
        y = int(h * 0.20 + h * 0.06 * amp * np.cos(self.frame_count / 9))

        # Simula confiança oscilando
        conf = 0.75 + 0.15 * abs(np.sin(self.frame_count / 30))
        return [{
            "box":        [x, y, bw, bh],
            "confidence": round(conf, 2),
            "label":      self.current_pet,
            "behavior":   BEHAVIOR_STATES[self.behavior_idx],
            "simulated":  True,
        }]


# ─── Atividade comportamental (Sprint 3) ──────────────────────────────────────
class ActivityTracker:
    """
    Transforma a visão computacional em sensor comportamental.

    Mede o deslocamento do centróide do bounding box entre frames (normalizado
    pela diagonal do frame), suaviza com EWMA e publica um activity_score 0..1
    no dashboard a cada ACTIVITY_PUSH_INTERVAL segundos. No Copilot, esse
    índice vira a feature act_z — "o pet está se mexendo menos que o normal DELE".
    """

    def __init__(self, pet_name: str = PET_NAME, url: str = DASHBOARD_ACTIVITY_URL,
                 alpha: float = 0.15, gain: float = 100.0):
        # gain calibra a escala: ~1% da diagonal por frame (pet andando) ≈ 1.0;
        # pet em repouso com pequenos movimentos ≈ 0.1 — mesma escala do MPU6050 simulado
        self.pet_name = pet_name
        self.url = url
        self.alpha = alpha
        self.gain = gain
        self.prev_center = None
        self.score = 0.0
        self.last_push = 0.0
        self.pushed = 0

    def update(self, detections, frame_shape) -> float:
        h, w = frame_shape[:2]
        diag = (w ** 2 + h ** 2) ** 0.5
        if detections:
            x, y, bw, bh = detections[0]["box"]
            center = (x + bw / 2, y + bh / 2)
            if self.prev_center is not None:
                disp = ((center[0] - self.prev_center[0]) ** 2 + (center[1] - self.prev_center[1]) ** 2) ** 0.5 / diag
                inst = min(1.0, disp * self.gain)
                self.score = (1 - self.alpha) * self.score + self.alpha * inst
            self.prev_center = center
        else:
            self.score *= (1 - self.alpha)     # pet fora de cena: índice decai
            self.prev_center = None

        now = time.time()
        if now - self.last_push >= ACTIVITY_PUSH_INTERVAL:
            self.last_push = now
            threading.Thread(target=self._push, daemon=True).start()
        return self.score

    def _push(self):
        try:
            requests.post(self.url, json={
                "pet_name": self.pet_name, "activity_score": round(self.score, 3),
                "timestamp": datetime.now().isoformat(timespec="seconds"), "source": "vision",
            }, timeout=1.5)
            self.pushed += 1
        except Exception:
            pass  # dashboard pode estar desligado; não interrompe a detecção


# ─── Renderização do HUD ──────────────────────────────────────────────────────
def draw_hud(frame, detections, fps, log_entries):
    """Desenha interface HUD completa sobre o frame."""
    h, w = frame.shape[:2]

    # ── Cabeçalho ──
    draw_panel(frame, 0, 0, w, 50)
    cv2.putText(frame, "CLYVO VET  |  Pet Health Monitoring",
                (12, 32), cv2.FONT_HERSHEY_SIMPLEX, 0.7, COLORS["accent"], 2)
    ts = datetime.now().strftime("%d/%m/%Y  %H:%M:%S")
    cv2.putText(frame, ts, (w - 240, 32),
                cv2.FONT_HERSHEY_SIMPLEX, 0.55, COLORS["info"], 1)

    # ── FPS ──
    cv2.putText(frame, f"FPS: {fps:.1f}", (w - 100, 70),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (180, 180, 180), 1)

    for det in detections:
        x, y, bw, bh = det["box"]
        label = det["label"]
        conf = det["confidence"]
        color = COLORS.get(label, COLORS["info"])

        # Bounding box
        cv2.rectangle(frame, (x, y), (x + bw, y + bh), color, 2)
        draw_rounded_rect(frame, (x, y), (x + bw, y + bh), color, 2)

        # Simulação de vitais
        vitals = simulate_vitals(label)
        health_msg, health_color = assess_health_alert(vitals, label)
        behavior = det.get("behavior", BEHAVIOR_STATES[0])

        # Painel lateral direito
        px, py, pw, ph = w - 230, 60, 225, 230
        draw_panel(frame, px, py, pw, ph, alpha=0.75)

        species = "Cão" if label == "dog" else "Gato"
        lines = [
            ("Espécie",      species,                          COLORS["accent"]),
            ("Confiança",    f"{conf * 100:.1f}%",             COLORS["info"]),
            ("Comportamento",behavior,                         COLORS["info"]),
            ("Temperatura",  f"{vitals['temperature']} ºC",   COLORS["info"]),
            ("Freq. Card.",  f"{vitals['heart_rate']} bpm",   COLORS["info"]),
            ("Freq. Resp.",  f"{vitals['resp_rate']} mpm",    COLORS["info"]),
        ]
        for i, (key, val, col) in enumerate(lines):
            yy = py + 22 + i * 32
            cv2.putText(frame, f"{key}:", (px + 8, yy),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.45, (180, 180, 180), 1)
            cv2.putText(frame, val, (px + 8, yy + 14),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, col, 1)

        # Alerta de saúde
        ay = py + ph + 8
        draw_panel(frame, px, ay, pw, 36, color=(0, 0, 60) if "ALERTA" in health_msg else (0, 40, 0), alpha=0.8)
        cv2.putText(frame, health_msg[:28], (px + 6, ay + 24),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.42, health_color, 1)

        # Label acima do bounding box
        tag = f"{species}  {conf * 100:.0f}%"
        (tw, th), _ = cv2.getTextSize(tag, cv2.FONT_HERSHEY_SIMPLEX, 0.55, 1)
        cv2.rectangle(frame, (x, y - th - 10), (x + tw + 8, y), color, -1)
        cv2.putText(frame, tag, (x + 4, y - 6),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 0), 1)

        # Indicador de simulação
        if det.get("simulated"):
            cv2.putText(frame, "[SIMULADO]", (12, h - 14),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.45, (100, 100, 255), 1)

    # ── Log de eventos ──
    lx, lh_max = 10, 100
    ly = h - lh_max - 10
    draw_panel(frame, lx, ly, 380, lh_max, alpha=0.55)
    cv2.putText(frame, "Eventos recentes:", (lx + 6, ly + 16),
                cv2.FONT_HERSHEY_SIMPLEX, 0.4, COLORS["accent"], 1)
    for i, entry in enumerate(log_entries[-4:]):
        cv2.putText(frame, entry, (lx + 6, ly + 32 + i * 18),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.38, (200, 200, 200), 1)

    return frame


# ─── Logger de eventos ────────────────────────────────────────────────────────
class EventLogger:
    def __init__(self, path="logs/events.json"):
        os.makedirs("logs", exist_ok=True)
        self.path = path
        self.events = []

    def log(self, event_type: str, details: dict):
        entry = {
            "timestamp": datetime.now().isoformat(),
            "type":      event_type,
            **details,
        }
        self.events.append(entry)
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self.events, f, ensure_ascii=False, indent=2)
        ts = datetime.now().strftime("%H:%M:%S")
        return f"[{ts}] {event_type}: {details.get('label', '')} {details.get('message', '')}"


# ─── Pipeline Principal ───────────────────────────────────────────────────────
def run_detection(source=0):
    """
    Executa o pipeline de detecção.
    source: 0 = webcam, ou caminho para arquivo de vídeo/imagem.
    """
    print("=" * 60)
    print("  CLYVO VET — Pet Vision System  |  FIAP 2026")
    print("=" * 60)

    # Tenta carregar YOLO; usa simulação se não encontrar
    weights = "models/yolov4-tiny.weights"
    config  = "models/yolov4-tiny.cfg"
    coco_names_path = "models/coco.names"

    net = load_yolo_model(weights, config)
    sim = SimulatedDetector() if net is None else None
    coco_names = []
    if net and os.path.exists(coco_names_path):
        with open(coco_names_path) as f:
            coco_names = f.read().strip().split("\n")
    output_layers = get_output_layers(net) if net else []

    logger = EventLogger()
    log_entries = []
    tracker = ActivityTracker()          # Sprint 3 — visão como sensor comportamental
    activity = 0.0

    cap = cv2.VideoCapture(source)
    if not cap.isOpened():
        print(f"[ERRO] Não foi possível abrir a fonte de vídeo: {source}")
        print("       Gerando frames de demonstração sintéticos...")
        cap = None

    prev_time = time.time()
    frame_count = 0
    last_detected_label = None

    print("\nControles:")
    print("  Q / ESC  → Sair")
    print("  S        → Salvar screenshot")
    print("  R        → Resetar log\n")

    os.makedirs("screenshots", exist_ok=True)

    while True:
        if cap:
            ret, frame = cap.read()
            if not ret:
                break
        else:
            # Frame sintético de demonstração
            frame = np.zeros((480, 720, 3), dtype=np.uint8)
            cv2.putText(frame, "Fonte de video nao disponivel",
                        (60, 240), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (80, 80, 80), 2)

        frame_count += 1
        curr_time = time.time()
        fps = 1.0 / (curr_time - prev_time + 1e-9)
        prev_time = curr_time

        # Detecção
        if net:
            detections = detect_pets_yolo(frame, net, output_layers, coco_names)
            for d in detections:
                d["behavior"] = BEHAVIOR_STATES[frame_count % len(BEHAVIOR_STATES)]
        else:
            detections = sim.detect(frame)

        # Sprint 3 — índice de atividade a partir do movimento do bounding box
        activity = tracker.update(detections, frame.shape)

        # Registra eventos novos
        for det in detections:
            label = det["label"]
            vitals = simulate_vitals(label)
            health_msg, _ = assess_health_alert(vitals, label)
            if label != last_detected_label:
                entry = logger.log("PET_DETECTED", {
                    "label": label,
                    "confidence": det["confidence"],
                    "message": f"confiança {det['confidence'] * 100:.0f}%",
                })
                log_entries.append(entry)
                last_detected_label = label
            if "ALERTA" in health_msg:
                entry = logger.log("HEALTH_ALERT", {"label": label, "message": health_msg})
                log_entries.append(entry)

        # Renderiza HUD (+ índice de atividade publicado no Copilot)
        frame = draw_hud(frame, detections, fps, log_entries)
        cv2.putText(frame, f"Atividade (visao -> Copilot): {activity:.2f}   envios: {tracker.pushed}",
                    (12, 72), cv2.FONT_HERSHEY_SIMPLEX, 0.5, COLORS["accent"], 1)
        cv2.imshow("CLYVO VET — Pet Health Vision", frame)

        key = cv2.waitKey(1) & 0xFF
        if key in (ord("q"), 27):
            break
        elif key == ord("s"):
            path = f"screenshots/pet_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
            cv2.imwrite(path, frame)
            log_entries.append(f"[{datetime.now().strftime('%H:%M:%S')}] Screenshot salvo: {path}")
            print(f"  Screenshot salvo em {path}")
        elif key == ord("r"):
            log_entries.clear()

    if cap:
        cap.release()
    cv2.destroyAllWindows()
    print(f"\n  Sessão encerrada. {len(logger.events)} eventos registrados em logs/events.json")


# ─── Entrada ──────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys
    source = sys.argv[1] if len(sys.argv) > 1 else 0
    # Aceita inteiro (índice de câmera) ou string (caminho de arquivo/vídeo)
    try:
        source = int(source)
    except ValueError:
        pass
    run_detection(source)
