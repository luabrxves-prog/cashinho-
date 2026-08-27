# Cashinho

Plataforma de análise quantitativa, backtesting, paper trading e apoio operacional
para ativos da B3.

> **Estado atual: fundação (v0.1.0).**
> Não há estratégias, scanner, provedor de dados nem integração com corretora.
> **Nenhuma ordem real é enviada por esta aplicação.**

## Princípio

O Cashinho não procura operações a qualquer custo. Os estados válidos de uma
oportunidade são:

`SETUP APROVADO` · `AGUARDANDO GATILHO` · `SETUP REJEITADO` · `NÃO OPERAR` · `EXPIRADO`

`NÃO OPERAR` é uma decisão perfeitamente válida.

Antes de qualquer evolução para dinheiro real, a base de estudo fica registrada
em [`docs/STRATEGY_RESEARCH_BASE.md`](docs/STRATEGY_RESEARCH_BASE.md). Ela
documenta os princípios usados no Modo Estudo Profundo: mercado antes do ativo,
ativo antes do timeframe, timeframe antes do gatilho e risco em reais antes da
boleta.

A validação contra situações históricas fica em
[`docs/HISTORICAL_SCENARIO_TESTING.md`](docs/HISTORICAL_SCENARIO_TESTING.md).
Ela roda uma bateria de cenários via `scripts/run_scenario_suite.py` e marca
como `SKIP` qualquer janela que ainda não tenha CSV real local.
Com o MT5 aberto, `scripts/export_mt5_history.py` exporta candles reais para
`data/historical/` antes da bateria.
A bateria ampliada de 2020 a 2026 fica em
[`docs/scenario_suite_2020_2026.json`](docs/scenario_suite_2020_2026.json), com
contexto de noticias em [`docs/news_catalysts_2020_2026.json`](docs/news_catalysts_2020_2026.json).
O diagnostico por ativo, ano, mes, horario, regime e motivo de saida fica em
[`docs/BACKTEST_DIAGNOSTICS.md`](docs/BACKTEST_DIAGNOSTICS.md).
O estudo operacional 2020-2026 usado como base do Scanner B3 fica em
[`docs/DEEP_STUDY_2020_2026.md`](docs/DEEP_STUDY_2020_2026.md).

## Requisitos

- Python 3.11 ou superior

## Instalação

```bash
python -m venv .venv
# Linux/macOS
source .venv/bin/activate
# Windows
.venv\Scripts\activate

pip install -e .
pip install pytest pytest-cov ruff mypy
```

## Configuração

```bash
cp .env.example .env      # Windows: copy .env.example .env
```

O `.env` **nunca** é versionado. Apenas o `.env.example` vai para o repositório.
Nenhuma credencial de corretora é usada nesta fase.

## Dados de desenvolvimento

```bash
python scripts/generate_fixtures.py
```

Gera séries **sintéticas e determinísticas** em `data/fixtures/` (três ativos,
cinco timeframes). Não são preços reais da B3: servem para exercitar o pipeline
sem depender de rede. Backtest sobre esses arquivos mede o código, nunca a
estratégia.

Os arquivos não são versionados — a geração é reprodutível a partir da semente e
da data-âncora fixas no script.

## Execução

```bash
streamlit run app/main.py
```

A aplicação abre no modo definido em `CASHINHO_MODE`. O padrão é `PAPER`, e o modo
fica visível de forma permanente na barra lateral de todas as páginas.

## Testes

```bash
pytest                       # suíte completa
pytest -m "not integration"  # apenas testes unitários
pytest --cov=cashinho        # com cobertura
ruff check . && mypy         # lint e tipos
```

## Modos de operação

| Modo | Estado |
|---|---|
| `RESEARCH` | habilitado |
| `BACKTEST` | habilitado |
| `REPLAY` | habilitado |
| `PAPER` | habilitado (padrão) |
| `ASSISTED` | **bloqueado em runtime** |
| `LIVE` | **bloqueado em runtime** |

`ASSISTED` e `LIVE` são recusados por `Settings.ensure_mode_allowed()` enquanto o
provedor em tempo real, o Risk Manager completo e o gerador de boleta validado não
existirem. A falha acontece no arranque, não no envio de uma ordem.

## Ciclo PAPER

O fluxo operacional cobre entrada, acompanhamento e encerramento:

1. `FinalDecision` responde somente `ENTRADA LIBERADA` ou `NÃO ENTRAR`.
2. Após o fill, `PositionManager` responde `MANTER POSIÇÃO` ou `SAIR DA POSIÇÃO`.
3. STOP/TARGET têm prioridade e, sem sequência intrabar, STOP vence o empate.
4. Saída dinâmica exige bid para encerrar BUY e ask para encerrar SELL; nenhum
   preço é substituído por `last`.
5. `PaperBroker` realiza a transição, o P&L compartilhado calcula o resultado e o
   diário grava eventos idempotentes.
6. O backtest compara STOP+TARGET contra STOP+TARGET+PositionManager, inclusive
   por motivo de encerramento.

Não há trailing stop nesta versão e nenhum sinal contrário faz reversão
automática: primeiro a posição atual é encerrada, sempre no ambiente PAPER.

## Estrutura

```text
src/cashinho/
├── config/       configuração central e hash de reprodutibilidade
├── domain/       modelos puros (Pydantic), sem I/O
├── ports/        Protocols: Clock, MarketDataProvider
├── core/         regras e cálculo (time, data_quality)
├── adapters/     persistência, provedores, geração de boleta
└── observability/ logging estruturado

app/              interface Streamlit (camada fina, sem regra de negócio)
tests/            unit, integration e golden
```

## Regras de desenvolvimento

1. **Tempo.** É proibido chamar `datetime.now()` dentro de `src/cashinho/`.
   Toda leitura de tempo passa pela porta `Clock`.
2. **Fuso.** Interno sempre UTC e *aware*. Datetime naive é rejeitado na validação.
   A conversão para horário local só acontece na apresentação.
3. **Candle fechado.** Indicadores e motores de decisão recebem séries via
   `closed_only()` ou `require_closed()`. Nunca a série crua.
4. **Precisão.** `Decimal` para preço, quantidade e resultado. `float` apenas
   dentro do pipeline numérico, com conversão explícita em `CandleSeries.to_frame()`.
5. **Dados.** Nenhuma cotação é inventada e preço antigo nunca é apresentado como
   atual. Sem dados válidos, o resultado é `ANÁLISE BLOQUEADA`.
6. **Risco.** O Risk Manager tem autoridade superior à estratégia. Estratégias não
   enviam ordens: produzem oportunidades.
7. **Segredos.** Nenhuma credencial no repositório. Somente variáveis de ambiente.

## Limitações declaradas nesta versão

- O único provedor é `CsvHistoricalProvider`, que lê arquivos locais. Não há
  cotação ao vivo: `get_quote()` falha por princípio, em vez de devolver o último
  fechamento como se fosse preço atual.
- As séries de desenvolvimento são sintéticas. Nenhum dado real da B3 está integrado.
- A tela de Análise executa inspeção histórica (`RESEARCH`) mesmo com o sistema em
  `PAPER`, porque a fonte atual não fornece tempo real. O rebaixamento é declarado
  na própria tela.
- O calendário de feriados da B3 não está carregado; dias úteis são aproximados.
- O schema do banco é criado com `create_all`. O Alembic assume as migrações na
  Fase 6, antes de o diário acumular dados que não possam ser perdidos.
- Os limites de risco vêm de valores padrão de configuração, não do estado
  operacional real.
- O Position Manager usa stop e target fixos. A arquitetura admite uma política
  futura de trailing stop, mas ela não foi implementada.
- Saídas dinâmicas do PAPER dependem de book ativo; sem bid/ask, a interface mostra
  a recomendação e mantém a posição aberta.
- O backtest executa saídas dinâmicas no fechamento conhecido do candle operacional;
  não modela sequência intrabar além da regra conservadora de STOP.
