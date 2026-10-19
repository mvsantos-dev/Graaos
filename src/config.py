"""Configurações do Graaos (módulo Fertilizantes).

Tudo aqui é público. Segredos, se um dia existirem, vêm SOMENTE de variáveis de
ambiente (veja .env.example) e nunca são escritos em código.
"""

from __future__ import annotations

from pathlib import Path
from urllib.parse import urlsplit

# --- Caminhos -------------------------------------------------------------------
RAIZ = Path(__file__).resolve().parent.parent
DADOS_DIR = RAIZ / "data"
RAW_DIR = DADOS_DIR / "raw"
PROCESSED_DIR = DADOS_DIR / "processed"
NCM_CSV = DADOS_DIR / "ncm_fertilizantes.csv"
# Um arquivo por ano, em partição no estilo Hive: data/raw/ano=AAAA/importacoes.parquet
RAW_ARQUIVO = "importacoes.parquet"
# Exportação de soja em grão (relação de troca): data/raw_soja/ano=AAAA/exportacoes.parquet
RAW_SOJA_DIR = DADOS_DIR / "raw_soja"
RAW_SOJA_ARQUIVO = "exportacoes.parquet"
# Insumos do fósforo (enxofre e rocha fosfática): NCMs num CSV próprio e importações com as
# mesmas colunas das de fertilizantes, em data/raw_insumos/ano=AAAA/importacoes.parquet. Ficam
# fora de data/raw: nunca entram nos totais de fertilizantes.
NCM_INSUMOS_CSV = DADOS_DIR / "ncm_insumos.csv"
RAW_INSUMOS_DIR = DADOS_DIR / "raw_insumos"
# Boletim mensal com IA (fase 5): boletins/AAAA-MM.md e boletins/latest.json
BOLETINS_DIR = RAIZ / "boletins"

# --- API Comex Stat (dados abertos do MDIC, sem autenticação) --------------------
# Documentação: https://api-comexstat.mdic.gov.br/docs (spec OpenAPI em /docs/doc.yaml)
API_BASE_URL = "https://api-comexstat.mdic.gov.br"
API_HOST = urlsplit(API_BASE_URL).hostname
IDIOMA = "pt"
USER_AGENT = "graaos (+https://github.com/mvsantos-dev/graaos)"

ENDPOINT_CONSULTA = "/general"
ENDPOINT_ULTIMA_ATUALIZACAO = "/general/dates/updated"
ENDPOINT_NCM = "/tables/ncm"
ENDPOINT_PAISES = "/tables/countries"
ENDPOINT_UFS = "/tables/uf"
ENDPOINT_VIAS = "/tables/ways"

FLUXO = "import"
PRIMEIRO_MES = "1997-01"  # início da série mensal da API
# Detalhamentos (GET /general/details): país de origem, NCM, UF do produto, via e URF.
DETALHES = ["country", "ncm", "state", "via", "urf"]
# Métricas (GET /general/metrics) -> colunas gravadas no Parquet.
METRICAS = {
    "metricFOB": "vl_fob",  # US$ FOB
    "metricKG": "kg_liquido",  # quilograma líquido
    "metricCIF": "vl_cif",  # US$ CIF (só importação)
    "metricFreight": "vl_frete",  # US$ frete (só importação)
    "metricInsurance": "vl_seguro",  # US$ seguro (só importação)
}

# Soja em grão exceto para semeadura (confirmado em /tables/ncm/12019000): exportação mensal.
NCM_SOJA = "12019000"
METRICAS_SOJA = {"metricFOB": "vl_fob", "metricKG": "kg_liquido"}

# --- Rate limiting -----------------------------------------------------------------
# A API responde HTTP 429 ("tente novamente em 10 segundos") a chamadas em sequência.
PAUSA_ENTRE_CHAMADAS_S = 10.0
MAX_TENTATIVAS = 6
BACKOFF_BASE_S = 10.0  # 10, 20, 40, 80, 160 s...
BACKOFF_MAX_S = 300.0
TIMEOUT_S = (15, 180)  # (conexão, leitura)

# --- SSL ---------------------------------------------------------------------------
# Opcional: arquivo PEM ou DER com CAs extras (ex.: cadeia ICP-Brasil), somado ao
# bundle padrão na verificação TLS. A verificação nunca é desligada por padrão.
ENV_CA_EXTRA = "COMEXSTAT_CA_BUNDLE"

# --- Fase 6: benchmark internacional (Banco Mundial) e câmbio (BCB) ----------------------
# Banco Mundial, Commodity Price Data (The Pink Sheet), CC BY 4.0. A URL do xlsx muda a cada
# edição; ela é procurada na página Commodity Markets.
RAW_BENCHMARK_DIR = DADOS_DIR / "raw_benchmark"
PINK_ARQUIVO = "pink_sheet_mensal.csv"
PINK_FONTE = "fonte.json"
PINK_PAGINA = "https://www.worldbank.org/en/research/commodity-markets"
PINK_HOST_ARQUIVO = "thedocs.worldbank.org"
PINK_NOME_ARQUIVO = "CMO-Historical-Data-Monthly.xlsx"
PINK_ABA = "Monthly Prices"
PINK_MAX_BYTES = 20 * 1024 * 1024
PINK_MAX_DESCOMPACTADO = 200 * 1024 * 1024  # o xlsx real descompacta para poucos MB
MAX_BYTES_PAGINA = 5 * 1024 * 1024  # página do Banco Mundial e JSON do SGS
# Nome da coluna no xlsx (sem espaços nem asteriscos nas pontas) -> coluna gravada.
PINK_SERIES = {
    "Urea": "ureia",
    "DAP": "dap",
    "TSP": "tsp",
    "Potassium chloride": "kcl",
    "Phosphate rock": "rocha_fosfatica",
}
# As comparadas com o Brasil: um mês só está publicado quando as quatro têm valor.
PINK_OBRIGATORIAS = ("ureia", "dap", "tsp", "kcl")
# Banco Central do Brasil, SGS (dados abertos, ODbL). 3698: taxa de câmbio livre, dólar
# americano (venda), média do período, mensal (média das PTAX de venda dos dias úteis).
RAW_CAMBIO_DIR = DADOS_DIR / "raw_cambio"
PTAX_ARQUIVO = "ptax_venda_media_mensal.csv"
SGS_URL = "https://api.bcb.gov.br/dados/serie/bcdata.sgs.{codigo}/dados"
SGS_PTAX_VENDA_MEDIA_MENSAL = 3698
SGS_JANELA_ANOS = 5
INICIO_FASE6 = "2015-01"
PAUSA_FONTES_S = 5.0
# Únicos hosts que o cliente das fontes externas acessa (inclusive em redirecionamentos).
HOSTS_FONTES = ("www.worldbank.org", "thedocs.worldbank.org", "api.bcb.gov.br")

# --- Fertilizantes (capítulo 31 do SH) ----------------------------------------------
# Grupo por posição (SH4)...
GRUPO_POR_SH4 = {"3102": "N", "3103": "P", "3104": "K", "3105": "NPK"}
# ...com exceções por subposição (SH6): DAP e MAP são fosfatados na convenção de mercado.
GRUPO_POR_SH6 = {"310530": "P", "310540": "P"}

# --- Insumos do fósforo (capítulo 25 do SH) -------------------------------------------
# Matérias-primas do MAP e do DAP, no grupo "INSUMOS", separado dos fertilizantes: enxofre
# (2503, vira ácido sulfúrico) e rocha fosfática (2510.10 não moída e 2510.20 moída). Granel
# líquido (2807 ácido sulfúrico, 2809 ácido fosfórico, 2814 amônia) fica fora do Graaos.
GRUPO_INSUMOS = "INSUMOS"
INSUMOS_POR_SH4 = {"2503": "enxofre", "2510": "rocha"}

# --- Sinais de preço e de volume (src/sinais.py) ----------------------------------------------
# Regras fixas em Python, sem IA, calculadas para cada mês da série só com os dados até ele (sem
# olhar o futuro). O data/sinais.json repete todos estes valores no campo "limites". Um sinal é
# "atencao" a partir do limite da regra e "forte" a partir do limite forte. Variações em %, que
# entram na comparação arredondadas como a frase do sinal as mostra (inteiro, meio para cima).
SINAIS_JSON = DADOS_DIR / "sinais.json"
# Proteção contra ruído: preço (CIF em US$/t) só em mês com pelo menos este volume do produto (e
# fora da amostra pequena do bloco de origem). Cada mês da janela de comparação passa pela mesma
# regra: o mês que não passa fica fora da conta.
SINAIS_VOLUME_MIN_T = 20_000
# Enxofre e rocha chegam em navios graneleiros maiores, poucas cargas por mês: limite próprio,
# escolhido pela distribuição mensal de data/raw_insumos (2015-01 a 2026-09), em que o 5º
# percentil dos dois fica perto de 60 mil t. Abaixo de 40 mil t (cerca de uma carga) o mês é raro e
# o preço é o de um navio só, que pode destoar dos vizinhos (como a rocha em 2025-06). Vale junto
# com a amostra pequena do bloco "insumos" (INSUMOS_CORTE_AMOSTRA_T).
SINAIS_VOLUME_MIN_T_PRODUTO = {"enxofre": 40_000, "rocha": 40_000}
# Alta ou queda contra a média: CIF do mês ÷ média simples do CIF dos 12 meses anteriores que
# passam no volume mínimo, com pelo menos 9 deles na janela.
SINAIS_MEDIA_MESES = 12
SINAIS_MEDIA_MIN_VALIDOS = 9
SINAIS_MEDIA_PCT = 20.0
SINAIS_MEDIA_FORTE_PCT = 40.0
# Variação em 3 meses: CIF do mês ÷ CIF de 3 meses antes (os dois meses com o volume mínimo).
SINAIS_VARIACAO_MESES = 3
SINAIS_VARIACAO_PCT = 15.0
SINAIS_VARIACAO_FORTE_PCT = 30.0
# Recorde: CIF acima do maior (ou abaixo do menor) de todos os meses válidos anteriores, só depois
# de 36 meses válidos, para os primeiros meses da série não virarem recorde trivial. Forte quando
# passa o recorde anterior por 5% ou mais.
SINAIS_RECORDE_MIN_MESES = 36
SINAIS_RECORDE_FORTE_PCT = 5.0
# Internacional na frente: a Pink Sheet do produto andou 10% ou mais em 2 meses (sem troca de base
# da série no intervalo) e o CIF do Brasil, nos mesmos 2 meses, andou no mesmo sentido menos da
# metade disso (ou ficou parado, ou foi ao contrário): o importado costuma reagir com atraso.
SINAIS_INTERNACIONAL_MESES = 2
SINAIS_INTERNACIONAL_PCT = 10.0
SINAIS_INTERNACIONAL_FORTE_PCT = 20.0
SINAIS_INTERNACIONAL_FRACAO = 0.5
# Troca no porto (t de soja por t de KCl, ureia e MAP) acima do percentil 90 dos meses válidos
# anteriores (interpolação linear), depois de 36 deles; forte acima do percentil 97,5. Válido = o
# fertilizante e a soja exportada com o volume mínimo no mês.
SINAIS_TROCA_PERCENTIL = 90.0
SINAIS_TROCA_FORTE_PERCENTIL = 97.5
SINAIS_TROCA_MIN_MESES = 36
# Ritmo de importação: toneladas do mês contra as do mesmo mês do ano anterior, que precisa ter o
# volume mínimo do produto (uma base quase sem compra daria variações sem sentido).
SINAIS_RITMO_PCT = 25.0
SINAIS_RITMO_FORTE_PCT = 50.0
