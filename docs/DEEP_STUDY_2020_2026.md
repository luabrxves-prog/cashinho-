# Estudo profundo 2020-2026

Este documento registra o estudo operacional usado para gerar a politica
historica padrao do Cashinho. Ele nao prova resultado futuro e nao autoriza
dinheiro real; serve para bloquear contextos que a propria maquina encontrou
como ruins.

## Comando executado

```powershell
python scripts/run_backtest_diagnostics.py --symbols PETR4,VALE3,ITUB4,BOVA11 --years 2020-2026 --timeframes 15m,60m,1D --decision-timeframe 60m --max-decision-points 300 --output-dir data\reports\diagnostics_full_2020_2026 --policy-path data\reports\deep_study\operational_policy.json --snapshot-policy-path src\cashinho\config\operational_policy.default.json
```

## Escopo

- Periodo: 2020 a 2026.
- Ativos: PETR4, VALE3, ITUB4 e BOVA11.
- Timeframes: 15m, 60m e 1D.
- Relogio de decisao: fechamento do 60m.
- Pontos de decisao: ate 300 por ativo/ano, espalhados cronologicamente.
- Operacoes concluidas analisadas: 124.

BOVA11 participou do carregamento e da avaliacao, mas nao gerou operacoes
concluidas nesse recorte. Por isso nao aparece no agrupamento por ativo.

## Resultado geral

| Recorte | Trades | Win rate | Profit factor | Resultado | Drawdown |
|---|---:|---:|---:|---:|---:|
| Total 15m | 124 | 33.87% | 1.25 | R$ 12.26 | 10.62% |

## Leitura ano a ano

| Ano | Trades | Win rate | Profit factor | Resultado | Drawdown |
|---|---:|---:|---:|---:|---:|
| 2024 | 21 | 19.05% | 0.46 | R$ -4.55 | 5.76% |
| 2023 | 11 | 9.09% | 0.33 | R$ -2.62 | 3.32% |
| 2026 | 13 | 30.77% | 1.11 | R$ 0.30 | 1.36% |
| 2022 | 20 | 30.00% | 1.07 | R$ 0.58 | 2.57% |
| 2020 | 14 | 42.86% | 1.40 | R$ 3.53 | 2.52% |
| 2025 | 24 | 54.17% | 2.11 | R$ 6.23 | 1.83% |
| 2021 | 21 | 38.10% | 1.80 | R$ 8.79 | 4.04% |

Essa tabela e a leitura principal do estudo. Os anos 2023 e 2024 aparecem como
alerta porque foram os piores, mas a politica nao pode ser calibrada olhando
apenas esses dois anos. O criterio correto e exigir que qualquer melhoria nova
seja comparada contra todos os recortes anuais acima.

## Como melhorar olhando todos os anos

1. Robustez anual antes de liberar real.

   Uma alteracao de estrategia so deve ser aceita se melhorar o conjunto
   2020-2026, nao apenas um ano isolado. A meta minima para continuar em PAPER
   deve ser: profit factor total maior, drawdown total menor e nenhum ano com
   deterioracao grave sem explicacao.

2. Tratar anos ruins como diagnostico, nao como unica fonte.

   2023 e 2024 mostram onde a logica quebrou. Eles servem para descobrir
   fragilidades, mas as novas travas precisam ser testadas tambem em 2020,
   2021, 2022, 2025 e 2026 para evitar ajuste excessivo ao passado.

3. Manter anos bons como protecao contra excesso de filtro.

   2020, 2021 e 2025 foram positivos no recorte. Se um filtro remove todos os
   trades bons desses anos, ele provavelmente esta deixando a maquina parada
   demais. Melhorar nao e apenas bloquear; e bloquear perdas preservando boas
   oportunidades.

4. Separar anos neutros de anos ruins.

   2022 e 2026 ficaram perto do zero. Eles devem medir se a estrategia
   sobrevive em mercado morno, sem depender de ano muito direcional.

5. Exigir comparativo antes/depois.

   Toda nova regra precisa gerar uma tabela antes/depois com os mesmos anos:
   trades, win rate, profit factor, resultado, drawdown e quantidade de sinais
   bloqueados. Sem esse comparativo, a regra nao entra na politica padrao.

## Leitura por ativo

| Ativo | Trades | Win rate | Profit factor | Resultado | Drawdown |
|---|---:|---:|---:|---:|---:|
| VALE3 | 29 | 27.59% | 1.26 | R$ 3.15 | 4.58% |
| ITUB4 | 48 | 39.58% | 1.20 | R$ 3.98 | 6.46% |
| PETR4 | 47 | 31.91% | 1.30 | R$ 5.13 | 5.96% |

## Contextos ruins encontrados

| Dimensao | Grupo | Trades | Win rate | Profit factor | Resultado | Acao |
|---|---:|---:|---:|---:|---:|---|
| Horario | 10:00 | 26 | 34.62% | 0.86 | R$ -0.66 | Bloquear |
| Regime | RANGE | 48 | 31.25% | 0.74 | R$ -4.05 | Bloquear |
| Regime | TREND_UP | 16 | 25.00% | 0.82 | R$ -0.73 | Bloquear |
| Volatilidade | LOW | 11 | 9.09% | 0.38 | R$ -2.06 | Bloquear |

Essas quatro regras foram salvas em
`src/cashinho/config/operational_policy.default.json` e usadas como fallback
automatico pelo Scanner B3 quando nao houver uma politica local mais nova em
`data/reports/deep_study/operational_policy.json`.

## Limites do estudo

- O estudo usa dados locais exportados do MT5/CSV; a procedencia precisa seguir
  visivel na interface.
- O recorte usa 15m como menor timeframe versionado. O 5m ainda exige um job
  mais otimizado para rodar o periodo inteiro sem custo excessivo.
- A politica gerada bloqueia contextos historicamente ruins; ela nao transforma
  nenhum contexto em garantia de acerto.
