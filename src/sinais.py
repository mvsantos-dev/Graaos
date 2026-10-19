"""Sinais automáticos de preço e de volume, por regras fixas em Python (sem IA).

Lê o data/processed/dashboard.json e, para cada mês da série e cada produto acompanhado, calcula
os sinais só com os dados até aquele mês: nenhuma regra olha o futuro, então o histórico mostra o
que teria disparado em cada mês. Grava tudo em data/sinais.json, num formato estável documentado
no README (o campo "versao" só muda se um campo sair ou mudar de sentido). Os limites ficam em
config.py (SINAIS_*) e voltam no campo "limites" do arquivo.

Produtos (as mesmas chaves do site, do feed e dos marcos de mercado) e de onde vêm as séries:
- ureia, sulfato_amonio, kcl, map, dap, tsp: bloco "nutrientes" (toneladas e CIF em US$/t, com os
  NCMs de src/comparacao.py);
- npk: grupo NPK do bloco "mensal";
- enxofre, rocha: bloco "insumos" (ficam de fora enquanto o dashboard.json não o tiver).
Pink Sheet: bloco "benchmark" (o MAP pelo DAP, aproximação) e, para a rocha, o do bloco "insumos".
Troca no porto (KCl, ureia e MAP): bloco "troca".

Mês válido para preço: volume do produto no mês de pelo menos o volume mínimo (20 mil t, com
limite próprio para enxofre e rocha), CIF presente e fora da amostra pequena do bloco de origem.
Toda janela de comparação usa só meses válidos. Regras (números = padrões de config.py):
- media_12m: CIF do mês válido contra a média simples do CIF dos 12 meses anteriores válidos
  (pelo menos 9); sinal a partir de ±20%, forte a partir de ±40%.
- variacao_3m: CIF do mês contra o de 3 meses antes, os dois válidos; ±15%, forte ±30%.
- recorde: CIF acima do maior (alta) ou abaixo do menor (queda) de todos os meses válidos
  anteriores, com pelo menos 36 deles; forte se passa o recorde anterior por 5% ou mais.
- internacional: Pink Sheet do produto com variação de ±10% ou mais em 2 meses, sem troca de base
  no intervalo, e CIF do Brasil (os dois meses válidos) que não acompanhou: andou no mesmo sentido
  menos da metade da variação da Pink Sheet (ou ficou parado, ou foi ao contrário). A direção é a
  da Pink Sheet; forte a partir de ±20%.
- troca_p90: troca no porto (t de soja por t de fertilizante) acima do percentil 90 (interpolação
  linear) dos meses válidos anteriores, com pelo menos 36 deles; forte acima do percentil 97,5.
  Válido aqui = fertilizante válido e soja exportada com o volume mínimo no mês.
- ritmo_importacao: toneladas do mês contra as do mesmo mês do ano anterior, que precisa ter o
  volume mínimo; ±25%, forte ±50%. Mês sem importação (zero t) conta como zero; mês sem dado
  (null: fora do período ingerido da série, como os insumos ainda não baixados) não entra.

A troca é "no porto", não o preço ao produtor, e é US$/US$ (não existe troca em reais). A Pink
Sheet é uma referência de outro lugar e de outro momento de contrato, não um preço do Brasil.

Só biblioteca padrão: o build do site (src/estatico) importa frase() e sinais_do_mes().

Uso:
    python -m src.sinais                 # grava data/sinais.json
    python -m src.sinais --mes 2026-09   # só mostra os sinais do mês, com a frase de cada um

Fonte: Comex Stat/MDIC; Banco Mundial (Pink Sheet).
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from . import config
from .estatico import formato as F

VERSAO = 1
FONTE = "Comex Stat/MDIC; Banco Mundial (Pink Sheet)"
DASHBOARD_JSON = config.PROCESSED_DIR / "dashboard.json"

# chave -> (nome nas frases, âncora do gráfico de preço do produto no site)
PRODUTOS = {
    "ureia": ("Ureia", "#secao-bm"),
    "sulfato_amonio": ("Sulfato de amônio", "#secao-nutrientes"),
    "kcl": ("KCl", "#secao-bm"),
    "map": ("MAP", "#secao-bm"),
    "dap": ("DAP", "#secao-bm"),
    "tsp": ("TSP", "#secao-bm"),
    "npk": ("NPK", "#precos"),
    "enxofre": ("Enxofre", "#grafico-enxofre"),
    "rocha": ("Rocha fosfática", "#grafico-rocha"),
}
INSUMOS = ("enxofre", "rocha")
ANCORA_TROCA = "#troca"
TIPOS = ("media_12m", "variacao_3m", "recorde", "internacional", "troca_p90", "ritmo_importacao")
NIVEIS = ("forte", "atencao")
DIRECOES = ("alta", "queda")
CASAS = 6  # como os blocos "benchmark" e "troca" do dashboard.json

CAMPOS = ("id", "mes", "produto", "tipo", "direcao", "metrica", "valor", "unidade", "comparacao", "nivel", "ancora", "frase")
METRICAS = {  # tipo -> (métrica, unidade)
    "media_12m": ("cif_usd_t", "US$/t"),
    "variacao_3m": ("cif_usd_t", "US$/t"),
    "recorde": ("cif_usd_t", "US$/t"),
    "internacional": ("pink_usd_t", "US$/t"),
    "troca_p90": ("troca_t_soja", "t de soja por t"),
    "ritmo_importacao": ("t", "t"),
}
BASES = {  # tipo -> comparacao.base (os números do nome são os padrões; os usados vão em "limites")
    "media_12m": "media_12m",
    "variacao_3m": "3_meses_antes",
    "recorde": "recorde_anterior",
    "internacional": "pink_2_meses_antes",
    "troca_p90": "percentil_90",
    "ritmo_importacao": "mesmo_mes_ano_anterior",
}
NOTAS = [
    "Sinais calculados mês a mês só com os dados até o mês (sem olhar o futuro), por regras fixas em"
    " Python (src/sinais.py), sem IA. Os limites de cada regra estão em \"limites\".",
    "Preço = CIF em US$/t (valor CIF ÷ toneladas importadas no mês). Só entram meses com o volume"
    " mínimo do produto; os outros ficam fora das médias, dos recordes e das comparações.",
    "Relação de troca no porto: CIF do fertilizante ÷ FOB da soja exportada no mesmo mês, em t de"
    " soja por t. Não é o preço ao produtor, e não muda com o câmbio.",
    "Pink Sheet (Banco Mundial): referência de outro lugar e de outro momento de contrato, não um"
    " preço do Brasil. O MAP usa o DAP como aproximação.",
    "O histórico é recalculado a cada atualização com os dados atuais: uma revisão das fontes pode"
    " mudar o sinal de um mês passado. O id (mês/produto/tipo) não muda.",
]


class ErroSinais(ValueError):
    """Arquivo de sinais fora do formato."""


# --- Limites ---------------------------------------------------------------------------------


def limites_config() -> dict:
    """Os limites de config.py (SINAIS_*), no formato do campo "limites" do sinais.json."""
    return {
        "volume_min_t": config.SINAIS_VOLUME_MIN_T,
        "volume_min_t_produto": dict(config.SINAIS_VOLUME_MIN_T_PRODUTO),
        "media_12m": {
            "meses": config.SINAIS_MEDIA_MESES,
            "min_meses_validos": config.SINAIS_MEDIA_MIN_VALIDOS,
            "limite_pct": config.SINAIS_MEDIA_PCT,
            "forte_pct": config.SINAIS_MEDIA_FORTE_PCT,
        },
        "variacao_3m": {
            "meses": config.SINAIS_VARIACAO_MESES,
            "limite_pct": config.SINAIS_VARIACAO_PCT,
            "forte_pct": config.SINAIS_VARIACAO_FORTE_PCT,
        },
        "recorde": {
            "min_meses_validos": config.SINAIS_RECORDE_MIN_MESES,
            "forte_pct": config.SINAIS_RECORDE_FORTE_PCT,
        },
        "internacional": {
            "meses": config.SINAIS_INTERNACIONAL_MESES,
            "limite_pct": config.SINAIS_INTERNACIONAL_PCT,
            "forte_pct": config.SINAIS_INTERNACIONAL_FORTE_PCT,
            "fracao_acompanhou": config.SINAIS_INTERNACIONAL_FRACAO,
        },
        "troca_p90": {
            "percentil": config.SINAIS_TROCA_PERCENTIL,
            "forte_percentil": config.SINAIS_TROCA_FORTE_PERCENTIL,
            "min_meses_validos": config.SINAIS_TROCA_MIN_MESES,
        },
        "ritmo_importacao": {
            "limite_pct": config.SINAIS_RITMO_PCT,
            "forte_pct": config.SINAIS_RITMO_FORTE_PCT,
        },
    }


# --- Séries por produto ----------------------------------------------------------------------


@dataclass
class Serie:
    """Séries mensais de um produto, alinhadas a mensal.periodos (None = sem dado)."""

    chave: str
    t: list
    cif: list
    pequena: list
    volume_min: float
    pink: list | None = None
    pink_serie: str | None = None
    pink_proxy: bool = False
    pink_base: list | None = None  # base da série da Pink Sheet em cada mês
    troca: list | None = None
    soja_t: list | None = None
    soja_min: float = 0

    def valido(self, i: int) -> bool:
        """Mês com preço que entra nas regras (volume mínimo, CIF presente, fora da amostra pequena)."""
        t, p = self.t[i], self.cif[i]
        return _num(t) and t >= self.volume_min and _num(p) and p > 0 and not self.pequena[i]

    def troca_valida(self, i: int) -> bool:
        return (
            self.troca is not None and self.valido(i) and _num(self.troca[i]) and self.troca[i] > 0
            and _num(self.soja_t[i]) and self.soja_t[i] >= self.soja_min
        )


def _num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def _alinhar(periodos_bloco, valores, periodos: list[str]) -> list:
    """Valores de um bloco nos meses de mensal.periodos (mês que o bloco não tem fica None)."""
    if valores is None:
        return [None] * len(periodos)
    if periodos_bloco is None or list(periodos_bloco) == list(periodos):
        if len(valores) != len(periodos):
            raise ErroSinais("série com tamanho diferente dos períodos")
        return list(valores)
    pos = dict(zip(periodos_bloco, valores))
    return [pos.get(p) for p in periodos]


def _bases_por_mes(bases, periodos: list[str]) -> list:
    """Base da série da Pink Sheet em cada mês: lista [{"desde", "base"}] ou uma base só."""
    if isinstance(bases, str) or bases is None:
        return [bases] * len(periodos)
    ordenadas = sorted(bases, key=lambda b: b["desde"])
    saida = []
    for p in periodos:
        atual = None
        for b in ordenadas:
            if b["desde"] <= p:
                atual = b["base"]
        saida.append(atual)
    return saida


def series(dados: dict, limites: dict) -> dict[str, Serie]:
    """Uma Serie por produto presente no dashboard.json, na ordem de PRODUTOS."""
    periodos = dados["mensal"]["periodos"]
    nutrientes = (dados.get("nutrientes") or {}).get("produtos") or {}
    insumos = dados.get("insumos") or {}
    bm = dados.get("benchmark") or {}
    troca = dados.get("troca") or {}

    def vol(chave):
        return limites["volume_min_t_produto"].get(chave, limites["volume_min_t"])

    saida = {}
    for chave in PRODUTOS:
        if chave == "npk":
            m = dados["mensal"].get("NPK")
            if not m:
                continue
            blocop, t, cif, pequena = periodos, m.get("t"), m.get("preco_cif"), None
        elif chave in INSUMOS:
            p = (insumos.get("produtos") or {}).get(chave)
            if not p:
                continue
            blocop, t, cif, pequena = insumos.get("periodos"), p.get("t"), p.get("cif"), p.get("amostra_pequena")
        else:
            p = nutrientes.get(chave)
            if not p:
                continue
            blocop = dados["nutrientes"].get("periodos")
            t, cif, pequena = p.get("t"), p.get("cif"), p.get("amostra_pequena")
        s = Serie(
            chave=chave,
            t=_alinhar(blocop, t, periodos),
            cif=_alinhar(blocop, cif, periodos),
            pequena=[bool(v) for v in _alinhar(blocop, pequena or [False] * len(blocop or periodos), periodos)],
            volume_min=vol(chave),
        )
        # Pink Sheet
        if chave == "rocha":
            ref = (insumos["produtos"]["rocha"] or {}).get("benchmark")
            if ref and ref.get("bm") is not None:
                s.pink = _alinhar(insumos.get("periodos"), ref["bm"], periodos)
                s.pink_serie = ref.get("serie")
                s.pink_base = _bases_por_mes(ref.get("base"), periodos)
        elif chave in (bm.get("produtos") or {}):
            ref = bm["produtos"][chave]
            if ref.get("bm") is not None:
                s.pink = _alinhar(bm.get("periodos"), ref["bm"], periodos)
                s.pink_serie = ref.get("serie")
                s.pink_proxy = bool(ref.get("proxy"))
                s.pink_base = _bases_por_mes(ref.get("bases"), periodos)
        # Troca no porto
        if chave in (troca.get("produtos") or {}) and troca["produtos"][chave].get("razao") is not None:
            s.troca = _alinhar(troca.get("periodos"), troca["produtos"][chave]["razao"], periodos)
            s.soja_t = _alinhar(troca.get("periodos"), troca.get("soja_t"), periodos)
            s.soja_min = limites["volume_min_t"]
        saida[chave] = s
    return saida


# --- Regras ----------------------------------------------------------------------------------


def _mes_menos(periodo: str, k: int) -> str:
    n = int(periodo[:4]) * 12 + int(periodo[5:7]) - 1 - k
    return f"{n // 12:04d}-{n % 12 + 1:02d}"


def _r(v: float) -> float:
    """6 casas, sem "-0.0"."""
    return round(v, CASAS) + 0.0


def _pct(atual: float, base: float) -> float:
    """Variação em %, já com as 6 casas gravadas (a decisão e a frase partem do mesmo número)."""
    return _r(100 * (atual / base - 1))


def _exibido(v: float, casas: int = 0) -> float:
    """O número como a frase o mostra (meio para cima, como o site): é ele que passa ou não no
    limite, para a frase nunca mostrar "40%" num sinal de atenção com limite forte de 40%."""
    return float(F.numero(v, casas, casas).replace(".", "").replace(",", "."))


def percentil(valores: list[float], p: float) -> float | None:
    """Percentil p (0 a 100) por interpolação linear entre os valores ordenados (o padrão do numpy)."""
    v = sorted(valores)
    if not v:
        return None
    x = (len(v) - 1) * p / 100
    baixo = math.floor(x)
    alto = min(baixo + 1, len(v) - 1)
    return v[baixo] + (v[alto] - v[baixo]) * (x - baixo)


class _Calculo:
    """As regras de um produto, mês a mês (cada uma só lê índices até o mês avaliado)."""

    def __init__(self, s: Serie, periodos: list[str], lim: dict):
        self.s, self.periodos, self.lim = s, periodos, lim
        self.pos = {p: i for i, p in enumerate(periodos)}
        self.ancora = PRODUTOS[s.chave][1]

    def antes(self, i: int, k: int) -> int | None:
        return self.pos.get(_mes_menos(self.periodos[i], k))

    def sinal(self, i, tipo, direcao, valor, comparacao, nivel, ancora=None) -> dict:
        mes = self.periodos[i]
        metrica, unidade = METRICAS[tipo]
        s = {
            "id": f"{mes}/{self.s.chave}/{tipo}",
            "mes": mes,
            "produto": self.s.chave,
            "tipo": tipo,
            "direcao": direcao,
            "metrica": metrica,
            "valor": valor,
            "unidade": unidade,
            "comparacao": {"base": BASES[tipo], **comparacao},
            "nivel": nivel,
            "ancora": ancora or self.ancora,
        }
        s["frase"] = frase(s)
        return s

    def media_12m(self, i: int) -> dict | None:
        lim, s = self.lim["media_12m"], self.s
        n = lim["meses"]
        if not s.valido(i) or self.antes(i, n) is None:
            return None
        meses = [self.antes(i, k) for k in range(1, n + 1)]
        janela = [s.cif[j] for j in meses if j is not None and s.valido(j)]
        if len(janela) < lim["min_meses_validos"]:
            return None
        media = math.fsum(janela) / len(janela)  # fsum: o sum() de floats mudou no Python 3.12
        var = _pct(s.cif[i], media)
        if abs(_exibido(var)) < lim["limite_pct"]:
            return None
        return self.sinal(
            i, "media_12m", "alta" if var > 0 else "queda", _r(s.cif[i]),
            {"valor": _r(media), "variacao_pct": var, "janela_meses": n, "meses_validos": len(janela)},
            "forte" if abs(_exibido(var)) >= lim["forte_pct"] else "atencao",
        )

    def variacao_3m(self, i: int) -> dict | None:
        lim, s = self.lim["variacao_3m"], self.s
        n = lim["meses"]
        j = self.antes(i, n)
        if j is None or not s.valido(i) or not s.valido(j):
            return None
        var = _pct(s.cif[i], s.cif[j])
        if abs(_exibido(var)) < lim["limite_pct"]:
            return None
        return self.sinal(
            i, "variacao_3m", "alta" if var > 0 else "queda", _r(s.cif[i]),
            {"mes": self.periodos[j], "valor": _r(s.cif[j]), "variacao_pct": var, "janela_meses": n},
            "forte" if abs(_exibido(var)) >= lim["forte_pct"] else "atencao",
        )

    def recorde(self, i: int) -> dict | None:
        lim, s = self.lim["recorde"], self.s
        if not s.valido(i):
            return None
        hist = [j for j in range(i) if s.valido(j)]
        if len(hist) < lim["min_meses_validos"]:
            return None
        jmax = max(hist, key=lambda j: (s.cif[j], -j))  # empate: vale o primeiro mês que chegou lá
        jmin = min(hist, key=lambda j: (s.cif[j], j))
        if s.cif[i] > s.cif[jmax]:
            direcao, j = "alta", jmax
        elif s.cif[i] < s.cif[jmin]:
            direcao, j = "queda", jmin
        else:
            return None
        var = _pct(s.cif[i], s.cif[j])
        return self.sinal(
            i, "recorde", direcao, _r(s.cif[i]),
            {"mes": self.periodos[j], "valor": _r(s.cif[j]), "variacao_pct": var, "desde": self.periodos[hist[0]], "meses_validos": len(hist)},
            "forte" if abs(var) >= lim["forte_pct"] else "atencao",
        )

    def internacional(self, i: int) -> dict | None:
        lim, s = self.lim["internacional"], self.s
        n = lim["meses"]
        j = self.antes(i, n)
        if s.pink is None or j is None:
            return None
        b0, b1 = s.pink[j], s.pink[i]
        if not (_num(b0) and _num(b1)) or b0 <= 0 or b1 <= 0:
            return None
        if any(s.pink_base[k] != s.pink_base[i] for k in range(j, i)):
            return None  # troca de base da série da Pink Sheet dentro do intervalo
        vp = _pct(b1, b0)
        if abs(_exibido(vp)) < lim["limite_pct"] or not s.valido(i) or not s.valido(j):
            return None
        vb = _pct(s.cif[i], s.cif[j])
        sentido = 1 if vp > 0 else -1
        if sentido * _exibido(vb) >= lim["fracao_acompanhou"] * abs(_exibido(vp)):
            return None  # o Brasil já acompanhou
        return self.sinal(
            i, "internacional", "alta" if vp > 0 else "queda", _r(b1),
            {
                "mes": self.periodos[j], "valor": _r(b0), "variacao_pct": vp, "janela_meses": n,
                "pink_serie": s.pink_serie, "proxy": s.pink_proxy,
                "brasil_valor": _r(s.cif[i]), "brasil_anterior": _r(s.cif[j]), "brasil_variacao_pct": vb,
            },
            "forte" if abs(_exibido(vp)) >= lim["forte_pct"] else "atencao",
        )

    def troca_p90(self, i: int) -> dict | None:
        lim, s = self.lim["troca_p90"], self.s
        if s.troca is None or not s.troca_valida(i):
            return None
        hist = [s.troca[j] for j in range(i) if s.troca_valida(j)]
        if len(hist) < lim["min_meses_validos"]:
            return None
        razao, p = _r(s.troca[i]), _r(percentil(hist, lim["percentil"]))
        # "acima" pelo número da frase (2 casas): nunca "1,05 t, acima do percentil 90 (1,05 t)"
        if not _exibido(razao, 2) > _exibido(p, 2):
            return None
        forte = _exibido(razao, 2) > _exibido(_r(percentil(hist, lim["forte_percentil"])), 2)
        return self.sinal(
            i, "troca_p90", "alta", razao,
            {"percentil": lim["percentil"], "valor": p, "variacao_pct": _pct(razao, p), "meses_validos": len(hist)},
            "forte" if forte else "atencao", ANCORA_TROCA,
        )

    def ritmo_importacao(self, i: int) -> dict | None:
        lim, s = self.lim["ritmo_importacao"], self.s
        j = self.antes(i, 12)
        # null não é zero: o bloco "insumos" deixa vazio o mês fora do período ingerido, e um
        # data/raw_insumos atrasado não pode virar "sem importação no mês"
        if j is None or not _num(s.t[i]) or not _num(s.t[j]) or s.t[j] < s.volume_min or s.t[j] <= 0:
            return None
        atual, base = int(round(s.t[i])), int(round(s.t[j]))
        var = _pct(atual, base)
        if abs(_exibido(var)) < lim["limite_pct"]:
            return None
        return self.sinal(
            i, "ritmo_importacao", "alta" if var > 0 else "queda", atual,
            {"mes": self.periodos[j], "valor": base, "variacao_pct": var},
            "forte" if abs(_exibido(var)) >= lim["forte_pct"] else "atencao",
        )


def _ordem(sinal: dict) -> tuple:
    return (sinal["mes"], NIVEIS.index(sinal["nivel"]), list(PRODUTOS).index(sinal["produto"]), TIPOS.index(sinal["tipo"]))


def calcular(dados: dict, limites: dict | None = None) -> list[dict]:
    """Todos os sinais de todos os meses, ordenados por mês, nível (forte primeiro), produto e tipo."""
    lim = limites or limites_config()
    periodos = dados["mensal"]["periodos"]
    sinais = []
    for s in series(dados, lim).values():
        calc = _Calculo(s, periodos, lim)
        regras = [getattr(calc, tipo) for tipo in TIPOS]
        for i in range(len(periodos)):
            sinais.extend(x for x in (regra(i) for regra in regras) if x)
    return sorted(sinais, key=_ordem)


def gerar(dados: dict, limites: dict | None = None) -> dict:
    """O conteúdo do data/sinais.json (sem data de geração: a saída é determinística)."""
    lim = limites or limites_config()
    periodos = dados["mensal"]["periodos"]
    presentes = series(dados, lim)
    return {
        "versao": VERSAO,
        "periodo": {"inicio": periodos[0], "fim": periodos[-1]},
        "fonte": FONTE,
        "limites": lim,
        "produtos": {
            k: {"nome": PRODUTOS[k][0], "ancora": PRODUTOS[k][1], "volume_min_t": s.volume_min, "pink_sheet": s.pink_serie}
            for k, s in presentes.items()
        },
        "notas": NOTAS,
        "sinais": calcular(dados, lim),
    }


# --- Frases ----------------------------------------------------------------------------------


def _pct_txt(v: float) -> str:
    return f"{F.fmt0(abs(v))}%"


def frase(sinal: dict) -> str:
    """Uma frase curta em pt-BR, com os números formatados como no site (src/estatico/formato)."""
    nome = PRODUTOS.get(sinal["produto"], (sinal["produto"],))[0]
    c, tipo, alta = sinal["comparacao"], sinal["tipo"], sinal["direcao"] == "alta"
    if tipo == "media_12m":
        return f"{nome}: CIF {_pct_txt(c['variacao_pct'])} {'acima' if alta else 'abaixo'} da média de {c['janela_meses']} meses"
    if tipo == "variacao_3m":
        return f"{nome}: CIF {'subiu' if alta else 'caiu'} {_pct_txt(c['variacao_pct'])} em {c['janela_meses']} meses"
    if tipo == "recorde":
        return f"{nome}: CIF de {F.por_tonelada(sinal['valor'])}, o {'maior' if alta else 'menor'} da série desde {F.rotulo_mes(c['desde'])}"
    if tipo == "internacional":
        ref = f"{c['pink_serie']} na Pink Sheet" if c.get("proxy") and c.get("pink_serie") else "Pink Sheet"
        vb = c["brasil_variacao_pct"]
        if F.fmt0(abs(vb)) == "0":
            brasil = "ficou estável"
        else:
            brasil = f"{'subiu' if vb > 0 else 'caiu'} {_pct_txt(vb)}"
        return f"{nome}: {ref} {'subiu' if alta else 'caiu'} {_pct_txt(c['variacao_pct'])} em {c['janela_meses']} meses; CIF do Brasil {brasil}"
    if tipo == "troca_p90":
        return (
            f"{nome}: troca no porto de {F.fmt2(sinal['valor'])} t de soja por t, acima do percentil"
            f" {F.numero(c['percentil'], 0, 1)} da série ({F.fmt2(c['valor'])} t)"
        )
    if tipo == "ritmo_importacao":
        mes = F.rotulo_mes(c["mes"])
        if sinal["valor"] == 0:
            return f"{nome}: sem importação no mês, contra {F.toneladas(c['valor'])} em {mes}"
        if not alta and F.fmt0(abs(c["variacao_pct"])) == "100":  # nunca "37 t importadas, 100% abaixo"
            return f"{nome}: só {F.toneladas(sinal['valor'])} importadas, contra {F.toneladas(c['valor'])} em {mes}"
        return f"{nome}: {F.toneladas(sinal['valor'])} importadas, {_pct_txt(c['variacao_pct'])} {'acima' if alta else 'abaixo'} de {mes}"
    raise ErroSinais(f"tipo de sinal desconhecido: {tipo!r}")


# --- Leitura, validação e consumo ---------------------------------------------------------------


def sinais_do_mes(dados: dict, mes: str) -> list[dict]:
    """Sinais de um mês, na ordem do arquivo (fortes primeiro).

    `dados` é o data/sinais.json já lido ou o dashboard.json (aí os sinais são calculados).
    """
    lista = dados["sinais"] if "sinais" in dados else calcular(dados)
    return [s for s in lista if s["mes"] == mes]


def validar(doc: dict) -> None:
    """Confere o formato do sinais.json (versão, campos, ordem, ids únicos e frases); ErroSinais se não."""
    if not isinstance(doc, dict) or doc.get("versao") != VERSAO:
        raise ErroSinais(f"versão do sinais.json diferente de {VERSAO}")
    for campo in ("periodo", "fonte", "limites", "produtos", "sinais"):
        if campo not in doc:
            raise ErroSinais(f"sinais.json sem o campo {campo!r}")
    mes_re = re.compile(r"\d{4}-(0[1-9]|1[0-2])")
    inicio, fim = doc["periodo"]["inicio"], doc["periodo"]["fim"]
    vistos = set()
    for s in doc["sinais"]:
        if tuple(s) != CAMPOS:
            raise ErroSinais(f"sinal com campos fora da ordem ou faltando: {list(s)}")
        if not mes_re.fullmatch(s["mes"]) or not inicio <= s["mes"] <= fim:
            raise ErroSinais(f"mês inválido: {s['mes']!r}")
        if s["produto"] not in PRODUTOS or s["produto"] not in doc["produtos"]:
            raise ErroSinais(f"produto desconhecido: {s['produto']!r}")
        if s["tipo"] not in TIPOS or s["nivel"] not in NIVEIS or s["direcao"] not in DIRECOES:
            raise ErroSinais(f"tipo, nível ou direção inválidos em {s['id']}")
        if s["id"] != f"{s['mes']}/{s['produto']}/{s['tipo']}" or s["id"] in vistos:
            raise ErroSinais(f"id inválido ou repetido: {s['id']!r}")
        vistos.add(s["id"])
        if (s["metrica"], s["unidade"]) != METRICAS[s["tipo"]] or not _num(s["valor"]):
            raise ErroSinais(f"métrica, unidade ou valor inválidos em {s['id']}")
        c = s["comparacao"]
        if c.get("base") != BASES[s["tipo"]] or not _num(c.get("valor")) or not _num(c.get("variacao_pct")):
            raise ErroSinais(f"comparação inválida em {s['id']}")
        if not isinstance(s["ancora"], str) or not s["ancora"].startswith("#"):
            raise ErroSinais(f"âncora inválida em {s['id']}")
        if s["frase"] != frase(s):
            raise ErroSinais(f"frase diferente da gerada em {s['id']}")
    if doc["sinais"] != sorted(doc["sinais"], key=_ordem):
        raise ErroSinais("sinais fora da ordem (mês, nível, produto, tipo)")


def ler(caminho: Path = config.SINAIS_JSON) -> dict:
    """data/sinais.json lido e validado."""
    doc = json.loads(Path(caminho).read_text(encoding="utf-8"))
    validar(doc)
    return doc


def serializar(doc: dict) -> str:
    """JSON com o cabeçalho indentado e um sinal por linha (diffs mensais curtos), chaves na ordem fixa."""
    cabeca = json.dumps({k: v for k, v in doc.items() if k != "sinais"}, ensure_ascii=False, indent=2, allow_nan=False)
    linhas = ",\n".join("    " + json.dumps(s, ensure_ascii=False, allow_nan=False) for s in doc["sinais"])
    lista = f"[\n{linhas}\n  ]" if linhas else "[]"
    return f'{cabeca[:-2]},\n  "sinais": {lista}\n}}\n'


def _mes(valor: str) -> str:
    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", valor):
        raise argparse.ArgumentTypeError(f"mês inválido: {valor!r} (use AAAA-MM)")
    return valor


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="python -m src.sinais",
        description="Sinais de preço e de volume por produto, mês a mês, a partir do dashboard.json."
        " Fonte: Comex Stat/MDIC; Banco Mundial (Pink Sheet).",
    )
    p.add_argument("--mes", type=_mes, metavar="AAAA-MM", help="só mostra os sinais desse mês, com as frases (não grava)")
    p.add_argument("--dashboard", type=Path, default=DASHBOARD_JSON, help="dashboard.json de entrada (padrão: %(default)s)")
    p.add_argument("--saida", type=Path, default=config.SINAIS_JSON, help="arquivo gravado (padrão: %(default)s)")
    args = p.parse_args(argv)
    try:
        dados = json.loads(args.dashboard.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        print(f"src.sinais: não consegui ler {args.dashboard}: {e}", file=sys.stderr)
        return 1
    doc = gerar(dados)
    faltam = [k for k in PRODUTOS if k not in doc["produtos"]]
    if faltam:
        print(f"src.sinais: aviso: sem dados no dashboard.json para {', '.join(faltam)} (ficam fora dos sinais)", file=sys.stderr)
    if args.mes:
        if args.mes not in dados["mensal"]["periodos"]:
            print(f"src.sinais: {args.mes} fora da série ({doc['periodo']['inicio']} a {doc['periodo']['fim']})", file=sys.stderr)
            return 1
        lista = sinais_do_mes(doc, args.mes)
        print(f"Sinais de {F.rotulo_mes_longo(args.mes)}: {len(lista) or 'nenhum'}")
        for s in lista:
            print(f"  {s['nivel']:<7} {s['frase']}  [{s['id']}, {s['ancora']}]")
        return 0
    validar(doc)
    args.saida.write_text(serializar(doc), encoding="utf-8")
    ultimo = sinais_do_mes(doc, doc["periodo"]["fim"])
    print(
        f"{len(doc['sinais'])} sinais de {doc['periodo']['inicio']} a {doc['periodo']['fim']} gravados em {args.saida}"
        f" ({len(ultimo)} em {doc['periodo']['fim']})."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
