"""
CLYVO VET - IoT Sensor Simulation
Disruptive Architectures: IoT, IoB & Generative IA - Sprint 3
FIAP 2026

Descrição:
    Simula o wearable do pet (ESP32 + sensores) publicando telemetria via HTTP
    para o dashboard. Evolução do Sprint 2:
      - MPU6050 simulado (acelerômetro) -> activity_score
      - Cenários de deriva gradual (--scenario fever|tachycardia|hypoxia|lethargy)
        para demonstrar a detecção pelo baseline individual do CLYVO Copilot
      - Calibração automática no baseline do pet (GET /api/pets/<id>/baseline):
        o "normal" simulado é o normal DAQUELE pet, não a média da espécie
      - Alertas por limite absoluto mantidos (última linha de defesa)

Uso:
    python iot_sensor_simulation.py                       # Thor, normal
    python iot_sensor_simulation.py --scenario fever      # febre gradual após 20 leituras
    python iot_sensor_simulation.py --pet Mel --species cat --scenario lethargy
"""

import argparse
import json
import math
import os
import random
import sys
import time
from datetime import datetime

import requests

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# ─── Configurações ────────────────────────────────────────────────────────────
DASHBOARD_URL = os.getenv("CLYVO_DASHBOARD_URL", "http://localhost:5000")
SENSOR_ENDPOINT = f"{DASHBOARD_URL}/api/sensor-data"
PUBLISH_INTERVAL_SECONDS = 2

# Faixas populacionais por espécie — limites ABSOLUTOS de segurança (Sprint 2)
NORMAL_RANGES = {
    "dog": {"temp": (37.5, 39.2), "hr": (60, 140), "spo2_min": 95},
    "cat": {"temp": (37.8, 39.2), "hr": (120, 220), "spo2_min": 95},
}

# Baseline padrão por espécie (usado se o dashboard não devolver o baseline individual)
SPECIES_DEFAULT = {
    "dog": {"temp": 38.5, "hr": 90.0, "spo2": 97.5, "act": 0.50},
    "cat": {"temp": 38.8, "hr": 160.0, "spo2": 97.5, "act": 0.45},
}

# Cenários: deslocamento máximo aplicado gradualmente (rampa) após --drift-after leituras
SCENARIOS = {
    "normal":      {},
    "fever":       {"temp": +1.3, "hr": +28, "act": -0.28},
    "tachycardia": {"hr": +50, "act": -0.10},
    "hypoxia":     {"spo2": -4.5, "hr": +15, "act": -0.20},
    "lethargy":    {"act": -0.35, "temp": +0.35},
}


# ─── Sensores Simulados ───────────────────────────────────────────────────────
class DHT22Sensor:
    """Simula sensor de temperatura e umidade DHT22."""

    def __init__(self, base_temp: float):
        self.base_temp = base_temp
        self._tick = 0

    def read(self, drift: float = 0.0) -> dict:
        self._tick += 1
        temp = self.base_temp + 0.15 * math.sin(self._tick / 20) + random.uniform(-0.08, 0.08) + drift
        humidity = 55.0 + 5 * math.sin(self._tick / 15) + random.uniform(-1, 1)
        return {"temperature_c": round(temp, 2), "humidity_pct": round(humidity, 1), "sensor": "DHT22"}


class HeartRateSensor:
    """Simula sensor de batimentos e oximetria (tipo MAX30102)."""

    def __init__(self, base_hr: float, base_spo2: float):
        self.base_hr = base_hr
        self.base_spo2 = base_spo2
        self._tick = 0

    def read(self, drift_hr: float = 0.0, drift_spo2: float = 0.0) -> dict:
        self._tick += 1
        hr = self.base_hr + 6 * math.sin(self._tick / 25) + random.randint(-3, 3) + drift_hr
        spo2 = self.base_spo2 - 0.4 * abs(math.sin(self._tick / 30)) + random.uniform(-0.2, 0.2) + drift_spo2
        return {"heart_rate_bpm": int(round(hr)), "spo2_pct": round(min(100.0, max(80.0, spo2)), 1),
                "sensor": "MAX30102-Simulated"}


class MotionSensor:
    """Simula acelerômetro MPU6050: índice de atividade 0..1 com ciclo circadiano."""

    def __init__(self, base_act: float):
        self.base_act = base_act
        self._tick = 0

    def read(self, drift: float = 0.0) -> dict:
        self._tick += 1
        # base_act já é a média histórica do pet (inclui o ciclo diário); aqui só um ajuste leve
        hour = datetime.now().hour
        circadian = 0.04 if 7 <= hour <= 21 else -0.08
        burst = 0.12 if (self._tick % 40) < 6 else 0.0          # picos curtos de brincadeira
        act = self.base_act + circadian + burst + 0.05 * math.sin(self._tick / 9) + random.uniform(-0.04, 0.04) + drift
        return {"activity_score": round(min(1.0, max(0.0, act)), 3), "sensor": "MPU6050-Simulated"}


class LCDDisplay:
    """Simula display LCD 16x2 (saída no terminal)."""

    WIDTH = 16

    def show(self, line1: str, line2: str = ""):
        def pad(s):
            return s[:self.WIDTH].ljust(self.WIDTH)
        border = "+" + "-" * self.WIDTH + "+"
        print(border)
        print(f"|{pad(line1)}|")
        print(f"|{pad(line2)}|")
        print(border)


# ─── Calibração no baseline individual ────────────────────────────────────────
def fetch_baseline(pet_name: str) -> tuple[dict | None, str | None]:
    """Pergunta ao dashboard qual é o 'normal' deste pet (média histórica dele)."""
    try:
        r = requests.get(f"{DASHBOARD_URL}/api/pets/lookup", params={"name": pet_name}, timeout=2)
        if r.status_code != 200:
            return None, None
        pet = r.json()
        b = requests.get(f"{DASHBOARD_URL}/api/pets/{pet['id']}/baseline", timeout=3).json()
        base = {k: b["baseline"][k]["mean"] for k in ("temp", "hr", "spo2", "act")}
        return base, pet["species"]
    except Exception:
        return None, None


# ─── Health Monitor ───────────────────────────────────────────────────────────
class PetHealthMonitor:
    """Agrega leituras dos sensores, aplica o cenário e publica no dashboard."""

    def __init__(self, pet_name: str, species: str, baseline: dict, scenario: str = "normal",
                 drift_after: int = 20, ramp: int = 30):
        self.name = pet_name
        self.species = species
        self.baseline = baseline
        self.scenario = scenario
        self.drift = SCENARIOS[scenario]
        self.drift_after = drift_after
        self.ramp = max(1, ramp)
        self.tick = 0
        self.dht22 = DHT22Sensor(baseline["temp"])
        self.hr_sensor = HeartRateSensor(baseline["hr"], baseline["spo2"])
        self.motion = MotionSensor(baseline["act"])
        self.lcd = LCDDisplay()
        self.history = []

    def drift_factor(self) -> float:
        if self.tick <= self.drift_after:
            return 0.0
        return min(1.0, (self.tick - self.drift_after) / self.ramp)

    def read_all(self) -> dict:
        self.tick += 1
        f = self.drift_factor()
        temp_data = self.dht22.read(f * self.drift.get("temp", 0.0))
        hr_data = self.hr_sensor.read(f * self.drift.get("hr", 0.0), f * self.drift.get("spo2", 0.0))
        act_data = self.motion.read(f * self.drift.get("act", 0.0))
        reading = {
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "pet_name": self.name,
            "species": self.species,
            "temperature_c": temp_data["temperature_c"],
            "humidity_pct": temp_data["humidity_pct"],
            "heart_rate_bpm": hr_data["heart_rate_bpm"],
            "spo2_pct": hr_data["spo2_pct"],
            "activity_score": act_data["activity_score"],
            "scenario": self.scenario,
            "drift_pct": round(100 * f),
            "source": "sensor",
        }
        reading["alerts"] = self._check_alerts(reading)
        return reading

    def _check_alerts(self, r: dict) -> list[str]:
        """Limites absolutos (Sprint 2). Última linha de defesa — a detecção fina é do Copilot."""
        lim = NORMAL_RANGES.get(self.species, NORMAL_RANGES["dog"])
        alerts = []
        if not (lim["temp"][0] <= r["temperature_c"] <= lim["temp"][1]):
            alerts.append(f"Temperatura fora do limite absoluto: {r['temperature_c']}°C")
        if not (lim["hr"][0] <= r["heart_rate_bpm"] <= lim["hr"][1]):
            alerts.append(f"FC fora do limite absoluto: {r['heart_rate_bpm']} bpm")
        if r["spo2_pct"] < lim["spo2_min"]:
            alerts.append(f"SpO2 abaixo do limite absoluto: {r['spo2_pct']}%")
        return alerts

    def update_display(self, r: dict):
        self.lcd.show(f"{self.name[:5]} {r['temperature_c']:.1f}C A{r['activity_score']:.2f}",
                      f"FC:{r['heart_rate_bpm']}bpm SpO2:{r['spo2_pct']:.0f}")

    def push_to_dashboard(self, r: dict):
        try:
            requests.post(SENSOR_ENDPOINT, json=r, timeout=2)
        except Exception:
            pass  # Dashboard pode não estar ativo; não interrompe o sensor

    def run(self, interval: float = PUBLISH_INTERVAL_SECONDS):
        print("=" * 58)
        print("  CLYVO VET — IoT Sensor Simulation (Sprint 3)")
        print(f"  Pet: {self.name}  |  Espécie: {self.species}  |  Cenário: {self.scenario}")
        print(f"  Baseline: T {self.baseline['temp']:.1f}°C  FC {self.baseline['hr']:.0f}  "
              f"SpO2 {self.baseline['spo2']:.1f}%  Act {self.baseline['act']:.2f}")
        if self.drift:
            print(f"  Deriva começa após {self.drift_after} leituras, rampa de {self.ramp}: {self.drift}")
        print("=" * 58)
        print("  Ctrl+C para encerrar\n")
        os.makedirs("logs", exist_ok=True)
        try:
            while True:
                r = self.read_all()
                self.history.append(r)
                self.update_display(r)
                tag = f"  | {self.scenario} {r['drift_pct']}%" if self.drift and r["drift_pct"] else ""
                print(f"  [{r['timestamp'][11:19]}] T {r['temperature_c']:.1f}°C  FC {r['heart_rate_bpm']} bpm  "
                      f"SpO2 {r['spo2_pct']}%  Act {r['activity_score']:.2f}{tag}")
                for alert in r["alerts"]:
                    print(f"  ⚠  ALERTA: {alert}")
                self.push_to_dashboard(r)
                with open("logs/sensor_history.json", "w", encoding="utf-8") as f:
                    json.dump(self.history[-200:], f, ensure_ascii=False, indent=2)
                time.sleep(interval)
        except KeyboardInterrupt:
            print(f"\n  Simulação encerrada. {len(self.history)} leituras salvas em logs/sensor_history.json")


# ─── Entrada ──────────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser(description="Simulador do wearable CLYVO VET")
    ap.add_argument("--pet", default="Thor", help="nome do pet cadastrado no dashboard")
    ap.add_argument("--species", choices=["dog", "cat"], default=None, help="usado se a calibração falhar")
    ap.add_argument("--scenario", choices=list(SCENARIOS), default="normal")
    ap.add_argument("--interval", type=float, default=PUBLISH_INTERVAL_SECONDS, help="segundos entre leituras")
    ap.add_argument("--drift-after", type=int, default=20, help="leituras antes de iniciar a deriva")
    ap.add_argument("--ramp", type=int, default=30, help="leituras para a deriva atingir 100%%")
    ap.add_argument("--no-calibrate", action="store_true", help="ignora o baseline individual do dashboard")
    args = ap.parse_args()

    baseline, species = (None, None) if args.no_calibrate else fetch_baseline(args.pet)
    species = args.species or species or "dog"
    if baseline:
        print(f"  Calibrado no baseline individual de {args.pet} (via dashboard).")
    else:
        baseline = dict(SPECIES_DEFAULT[species])
        print(f"  Dashboard indisponível ou pet desconhecido — usando baseline padrão ({species}).")

    PetHealthMonitor(args.pet, species, baseline, args.scenario, args.drift_after, args.ramp).run(args.interval)


if __name__ == "__main__":
    main()
