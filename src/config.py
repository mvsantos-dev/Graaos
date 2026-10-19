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
# Custo de insumo por tonelada de MAP (src/insumos.py) = CIF do enxofre × INSUMOS_COEF_ENXOFRE
# + CIF da rocha × INSUMOS_COEF_ROCHA. Aproximação técnica, não o custo de nenhuma empresa:
# toneladas de cada insumo por tonelada de MAP 11-52. O P2O5 do MAP vem do ácido fosfórico, feito
# atacando a rocha com ácido sulfúrico, que sai do enxofre. Rocha: 0,52 t de P2O5 por t de MAP ÷
# (cerca de 32% de P2O5 no concentrado × cerca de 95% de recuperação) ≈ 1,7 t. Enxofre: cerca de
# 2,7 t de ácido sulfúrico por t de P2O5 ≈ 1,4 t de ácido por t de MAP ≈ 0,45 t de enxofre (32/98
# do peso do ácido). O consumo real muda com o teor da rocha e o processo de cada fábrica.
INSUMOS_COEF_ENXOFRE = 0.45  # t de enxofre por t de MAP
INSUMOS_COEF_ROCHA = 1.7  # t de rocha fosfática por t de MAP
# Amostra pequena por insumo: mês com menos toneladas que isso fica marcado (preço de um navio
# só). Os dois chegam em graneleiros de 30 a 60 mil t por carga, e o mês típico traz várias cargas
# (mediana de 2015-01 a 2026-09: cerca de 180 mil t de enxofre e 145 mil t de rocha). Abaixo de 30
# mil t, menos de um navio cheio. Nesses dados, o corte marca 2 meses de enxofre (2016-03, 3 mil t,
# e 2023-07, 21 mil t, com CIF mais de 60% acima da mediana móvel de 5 meses; o mês seguinte em
# volume, com 42 mil t, fica a 4% dela) e 1 de rocha (2024-12, 21 mil t). O corte dos fertilizantes
# (comparacao.CORTE_AMOSTRA_T, 10 mil t) deixaria passar 2023-07.
INSUMOS_CORTE_AMOSTRA_T = {"enxofre": 30_000, "rocha": 30_000}
