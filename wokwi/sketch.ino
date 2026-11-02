/*
  CLYVO VET - IoT Wearable Pet Monitor
  Plataforma: ESP32
  Sensores:
    - DHT22 (temperatura/umidade)  → pino D4
    - LED piscante (batimentos)    → pino D2
    - Display LCD I2C 16x2         → SDA=D21, SCL=D22
    - Buzzer de alerta             → pino D5
  FIAP 2026 — Sprint 1
*/

#include <Arduino.h>
#include <DHT.h>
#include <LiquidCrystal_I2C.h>
#include <Wire.h>
#include <math.h>

// ── Pinos ────────────────────────────────────────────────────────────────────
#define DHT_PIN       4
#define DHT_TYPE      DHT22
#define HEART_LED_PIN 2
#define BUZZER_PIN    5

// ── Objetos ──────────────────────────────────────────────────────────────────
DHT dht(DHT_PIN, DHT_TYPE);
LiquidCrystal_I2C lcd(0x27, 16, 2);   // endereço I2C padrão 0x27

// ── Configuração do pet ───────────────────────────────────────────────────────
const char PET_NAME[]  = "Thor";
const char SPECIES[]   = "Cao";

// Faixas normais para cão
const float TEMP_MIN = 37.5, TEMP_MAX = 39.2;
const int   HR_MIN   = 60,   HR_MAX   = 140;

// ── Estado ────────────────────────────────────────────────────────────────────
int   heartRate   = 90;
float temperature = 38.5;
float humidity    = 55.0;
bool  alertActive = false;
unsigned long lastHRBeat   = 0;
unsigned long lastSensorRead = 0;
int   beatInterval = 667;  // ms entre batimentos (90 bpm ≈ 667ms)

// ── Caractere personalizado: coração ─────────────────────────────────────────
byte heartChar[8] = {
  0b00000, 0b01010, 0b11111, 0b11111,
  0b01110, 0b00100, 0b00000, 0b00000
};

// ── Funções ───────────────────────────────────────────────────────────────────

void setupLCD() {
  lcd.init();
  lcd.backlight();
  lcd.createChar(0, heartChar);
  lcd.setCursor(0, 0);
  lcd.print(" CLYVO VET IoT  ");
  lcd.setCursor(0, 1);
  lcd.print("  Iniciando...  ");
  delay(2000);
  lcd.clear();
}

float simulateTemperature(unsigned long t) {
  // Oscilação senoidal + ruído
  return 38.5 + 0.4 * sin(t / 20000.0) + (random(-10, 10) / 100.0);
}

int simulateHeartRate(unsigned long t) {
  return 90 + (int)(12 * sin(t / 25000.0)) + random(-5, 5);
}

void updateLCD(float temp, int hr, bool alert) {
  lcd.clear();
  // Linha 1: nome do pet e temperatura
  lcd.setCursor(0, 0);
  char line1[17];
  snprintf(line1, sizeof(line1), "%-5s %.1fC", PET_NAME, temp);
  lcd.print(line1);

  // Linha 2: batimentos + alerta
  lcd.setCursor(0, 1);
  lcd.write(byte(0));  // ícone de coração
  char line2[17];
  snprintf(line2, sizeof(line2), "%3d bpm %s", hr, alert ? "ALERTA!" : "Normal ");
  lcd.print(line2);
}

void checkAlerts(float temp, int hr) {
  bool tempAlert = (temp < TEMP_MIN || temp > TEMP_MAX);
  bool hrAlert   = (hr   < HR_MIN  || hr   > HR_MAX);
  alertActive = tempAlert || hrAlert;

  if (alertActive) {
    Serial.print("[ALERTA] ");
    if (tempAlert) { Serial.print("Temperatura: "); Serial.print(temp); Serial.print("C  "); }
    if (hrAlert)   { Serial.print("FC: "); Serial.print(hr); Serial.print("bpm"); }
    Serial.println();
    tone(BUZZER_PIN, 880, 200);
  }
}

void publishSerial(float temp, float hum, int hr) {
  // Saída JSON via Serial — pode ser lido por um gateway/script Python
  Serial.print("{\"pet\":\"");
  Serial.print(PET_NAME);
  Serial.print("\",\"species\":\"");
  Serial.print(SPECIES);
  Serial.print("\",\"temperature_c\":");
  Serial.print(temp, 2);
  Serial.print(",\"humidity_pct\":");
  Serial.print(hum, 1);
  Serial.print(",\"heart_rate_bpm\":");
  Serial.print(hr);
  Serial.print(",\"alert\":");
  Serial.print(alertActive ? "true" : "false");
  Serial.println("}");
}

// ── Setup ─────────────────────────────────────────────────────────────────────
void setup() {
  Serial.begin(115200);
  dht.begin();
  pinMode(HEART_LED_PIN, OUTPUT);
  pinMode(BUZZER_PIN, OUTPUT);
  setupLCD();

  Serial.println("=== CLYVO VET IoT — ESP32 Iniciado ===");
}

// ── Loop ──────────────────────────────────────────────────────────────────────
void loop() {
  unsigned long now = millis();

  // ── Leitura de sensores a cada 2s ──
  if (now - lastSensorRead >= 2000) {
    lastSensorRead = now;

    // DHT22 (no Wokwi, leitura real; em simulação pura, usamos função de simulação)
    float dhtTemp = dht.readTemperature();
    float dhtHum  = dht.readHumidity();

    if (isnan(dhtTemp)) {
      // Fallback: simulação senoidal
      temperature = simulateTemperature(now);
      humidity    = 55.0 + 5 * sin(now / 15000.0);
    } else {
      temperature = dhtTemp;
      humidity    = dhtHum;
    }

    heartRate = simulateHeartRate(now);
    beatInterval = 60000 / max(heartRate, 1);

    checkAlerts(temperature, heartRate);
    updateLCD(temperature, heartRate, alertActive);
    publishSerial(temperature, humidity, heartRate);
  }

  // ── Pisca LED no ritmo dos batimentos ──
  if (now - lastHRBeat >= (unsigned long)beatInterval) {
    lastHRBeat = now;
    digitalWrite(HEART_LED_PIN, HIGH);
    delay(60);   // pulso curto
    digitalWrite(HEART_LED_PIN, LOW);
  }
}
