"""
Guardrails — validação da saída generativa

O LLM redige; ele não decide. Esta camada garante que o texto que chega
ao tutor e ao veterinário:
  1. não contém diagnóstico afirmado nem prescrição/posologia
  2. está ancorado nos fatos (menciona o pet e uma ação de agendamento)
  3. respeita o tamanho do canal (WhatsApp)
  4. leva o aviso de responsabilidade do médico-veterinário (CFMV)

Se falhar, o pipeline descarta o texto e usa o template determinístico.
"""

import re

# Padrões proibidos em mensagens ao TUTOR (o veterinário recebe dados, não conselho)
FORBIDDEN_PATTERNS = [
    (r"\b\d+([.,]\d+)?\s?(mg|ml|mcg|g|comprimidos?|gotas?)\b", "posologia (dose numérica)"),
    (r"\b(prescrev|receit)\w*", "prescrição"),
    (r"\bdiagn[óo]stic\w*\s+(é|:|de|confirmad)", "diagnóstico afirmado"),
    (r"\b(está com|tem|é um caso de|apresenta)\s+(cinomose|parvovirose|leishmaniose|erliquiose|"
     r"insuficiência|infecção|pneumonia|câncer|tumor|diabetes|piometra|gastroenterite)\b", "doença afirmada"),
    (r"\b(dipirona|paracetamol|ibuprofeno|amoxicilina|antibi[óo]tico|corticoide|anti-?inflamat[óo]rio)\b",
     "medicamento nomeado"),
    (r"\b(administr|aplique|dê|dar)\s+\d", "instrução de administração"),
]

REQUIRED_ANY = ["agend", "consulta", "clínica", "clinica", "veterinári", "veterinari", "atendimento"]

DISCLAIMER = ("Mensagem gerada pelo CLYVO Copilot para revisão da equipe. "
              "Não substitui avaliação do médico-veterinário.")

MAX_TUTOR_CHARS = 700
MAX_VET_CHARS = 2500


def validate_tutor_message(text: str, pet_name: str) -> dict:
    violations = []
    if not text or len(text.strip()) < 20:
        violations.append("mensagem vazia ou muito curta")
        return {"ok": False, "violations": violations}

    low = text.lower()
    for pattern, label in FORBIDDEN_PATTERNS:
        if re.search(pattern, low, flags=re.IGNORECASE):
            violations.append(label)

    if pet_name and pet_name.lower() not in low:
        violations.append("não menciona o pet")
    if not any(k in low for k in REQUIRED_ANY):
        violations.append("sem chamada para ação (agendamento/consulta)")
    if len(text) > MAX_TUTOR_CHARS:
        violations.append(f"excede {MAX_TUTOR_CHARS} caracteres")

    return {"ok": not violations, "violations": violations}


def validate_vet_briefing(text: str) -> dict:
    violations = []
    if not text or len(text.strip()) < 40:
        violations.append("briefing vazio ou muito curto")
    elif len(text) > MAX_VET_CHARS:
        violations.append(f"excede {MAX_VET_CHARS} caracteres")
    # Para o vet, apenas posologia numérica é bloqueada (o sistema não prescreve)
    if text and re.search(FORBIDDEN_PATTERNS[0][0], text.lower()):
        violations.append("posologia (dose numérica)")
    return {"ok": not violations, "violations": violations}


def with_disclaimer(text: str) -> str:
    text = (text or "").rstrip()
    if DISCLAIMER.split(".")[0].lower() in text.lower():
        return text
    return f"{text}\n\n_{DISCLAIMER}_"
