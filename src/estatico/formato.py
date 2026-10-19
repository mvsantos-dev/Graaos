"""Os formatadores do dashboard (script do index.html) em Python, com a mesma saída.

O HTML gerado no build tem de mostrar exatamente o que o JavaScript desenha depois, então cada
função aqui espelha uma do script (nome entre parênteses). O arredondamento é o do Intl do
navegador: meio para cima, a partir do número como o JSON o grava (repr), igual ao _num do
boletim. O teste de navegador (tests/e2e/test_estatico.py) compara as duas saídas.
"""

from __future__ import annotations

import math
import re
from decimal import ROUND_HALF_UP, Decimal

MESES = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]
MESES_LONGOS = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"]
NOMES = {"N": "Nitrogenados", "P": "Fosfatados", "K": "Potássicos", "NPK": "Compostos (NPK)", "TOTAL": "Todos os grupos"}
GRUPOS = ["N", "P", "K", "NPK"]
MENOS = "−"  # U+2212, como o MENOS do script
TRACO = "–"  # valor ausente
NBSP = " "  # o Intl separa o número do "mil"/"mi"/"bi" com espaço inseparável

_COMPACTO = [(12, "tri"), (9, "bi"), (6, "mi"), (3, "mil")]


def nulo(v) -> bool:
    """(nulo) None ou NaN."""
    return v is None or (isinstance(v, float) and math.isnan(v))


def _decimal(valor: float) -> Decimal:
    return Decimal(repr(float(valor)))


def _agrupar(inteiro: str) -> str:
    """Milhar com ponto, como o pt-BR do Intl."""
    return re.sub(r"(?<=\d)(?=(\d{3})+$)", ".", inteiro)


def numero(valor: float, minimo: int = 0, maximo: int = 0) -> str:
    """Intl.NumberFormat("pt-BR", {minimumFractionDigits, maximumFractionDigits}).format(valor)."""
    original = _decimal(valor)
    d = original.quantize(Decimal(1).scaleb(-maximo), rounding=ROUND_HALF_UP)
    negativo = original.is_signed()  # o Intl mostra "-0" para -0,4 (e para -0)
    inteiro, _, fracao = f"{abs(d):f}".partition(".")
    fracao = fracao.rstrip("0")
    fracao = fracao + "0" * (minimo - len(fracao)) if len(fracao) < minimo else fracao
    texto = _agrupar(inteiro) + ("," + fracao if fracao else "")
    return ("-" if negativo else "") + texto


def fmt0(v: float) -> str:
    return numero(v, 0, 0)


def fmt1(v: float) -> str:
    return numero(v, 1, 1)


def fmt2(v: float) -> str:
    return numero(v, 2, 2)


def fmt4(v: float) -> str:
    return numero(v, 4, 4)


def compacto(valor: float) -> str:
    """(fmtCompacto) Intl.NumberFormat("pt-BR", {notation: "compact", maximumFractionDigits: 1})."""
    d = _decimal(valor)
    negativo = d.is_signed()
    a = abs(d)
    expoente, sufixo = 0, ""
    if a != 0:
        magnitude = a.adjusted()
        for exp, suf in _COMPACTO:
            if magnitude >= exp:
                expoente, sufixo = exp, suf
                break
    arredondado = a.scaleb(-expoente).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    # o arredondamento pode subir de ordem (999,95 mil vira 1 mi), como no ICU
    if arredondado >= 1000:
        maiores = [(e, s) for e, s in reversed(_COMPACTO) if e > expoente]
        if maiores:
            expoente, sufixo = maiores[0]
            arredondado = a.scaleb(-expoente).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    inteiro, _, fracao = f"{arredondado:f}".partition(".")
    fracao = fracao.rstrip("0")
    texto = _agrupar(inteiro) + ("," + fracao if fracao else "")
    if negativo:
        texto = "-" + texto
    return f"{texto}{NBSP}{sufixo}" if sufixo else texto


def toneladas(t) -> str:
    return TRACO if nulo(t) else f"{compacto(t)} t"


def dolares(v) -> str:
    return TRACO if nulo(v) else f"US$ {compacto(v)}"


def sinal_de(v: float, f, mais: str = "") -> str:
    """(sinalDe) sinal pelo número já arredondado: nunca "−0,0"."""
    return (MENOS if v < 0 else mais) if re.search(r"[1-9]", f(abs(v))) else ""


def com_sinal(v: float, f, mais: str = "") -> str:
    return f"{sinal_de(v, f, mais)}{f(abs(v))}"


def por_tonelada(v) -> str:
    return TRACO if nulo(v) else f"{sinal_de(v, fmt0)}US$ {fmt0(abs(v))}/t"


def pct(v) -> str:
    return TRACO if nulo(v) else f"{fmt1(v)}%"


def variacao(v, sufixo: str = "%") -> str:
    """(variacao) "▲ +5,3%", "▼ −27,9%" ou "■ 0,0%"."""
    if nulo(v) or not math.isfinite(v):
        return TRACO
    sinal = sinal_de(v, fmt1, "+")
    seta = "▲" if sinal == "+" else "▼" if sinal == MENOS else "■"
    return f"{seta} {sinal}{fmt1(abs(v))}{sufixo}"


def variacao_pct(atual, anterior):
    """(variacaoPct)"""
    return 100 * (atual / anterior - 1) if anterior is not None and anterior > 0 and not nulo(atual) else None


def rotulo_mes(p: str) -> str:
    """(rotuloMes) "set/2026"."""
    return f"{MESES[int(p[5:7]) - 1]}/{p[:4]}"


def rotulo_mes_longo(p: str) -> str:
    """(rotuloMesLongo) "setembro de 2026"."""
    return f"{MESES_LONGOS[int(p[5:7]) - 1]} de {p[:4]}"


_ACENTOS = {"PARANAGUA": "Paranaguá", "SAO": "São", "LUIS": "Luís", "VITORIA": "Vitória", "MACEIO": "Maceió", "SANTAREM": "Santarém"}
_MINUSCULAS = {"DE", "DO", "DA", "DOS", "DAS", "E"}
_SIGLAS = {"ALF", "IRF"}


def nome_urf(nome: str) -> str:
    """(nomeUrf) "PORTO DE PARANAGUA" vira "Porto de Paranaguá"."""
    if not nome or nome == "Outros":
        return nome
    partes = re.split(r"(\s+|/|-)", nome)
    saida = []
    for i, parte in enumerate(partes):
        if not any(c.isalpha() for c in parte):
            saida.append(parte)
            continue
        p = parte.upper()
        if p in _SIGLAS:
            saida.append(p)
        elif p in _ACENTOS:
            saida.append(_ACENTOS[p])
        elif p in _MINUSCULAS and i > 0:
            saida.append(p.lower())
        else:
            minusc = parte.lower()
            saida.append(minusc[:1].upper() + minusc[1:])
    return "".join(saida)


def nome_curto_urf(nome: str) -> str:
    """(nomeCurtoUrf) sem o "Porto de" do começo."""
    return re.sub(r"(^|- )Porto d[eo] ", r"\1", nome_urf(nome))
