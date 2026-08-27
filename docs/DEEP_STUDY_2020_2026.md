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

## Piores anos

| Ano | Trades | Win rate | Profit factor | Resultado | Drawdown |
|---|---:|---:|---:|---:|---:|
| 2024 | 21 | 19.05% | 0.46 | R$ -4.55 | 5.76% |
| 2023 | 11 | 9.09% | 0.33 | R$ -2.62 | 3.32% |

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
