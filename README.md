# alpine-hydro

Alpine hydro reservoirs and Swiss power prices. Work in progress; the full
README comes later.

![Swiss hydro storage](reports/figures/hero_storage.png)

Three parts:

- A. Satellite estimates of level and stored energy for seven large Swiss reservoirs.
- B. A pre-registered test of whether the Swiss storage deviation predicts the
  CH minus DE-LU day-ahead spread. See [prereg/PREREGISTRATION.md](prereg/PREREGISTRATION.md).
- C. A snowpack forecast of the summer refill.

## Quick start

```
uv sync
uv run alpinehydro demo      # rebuilds the chart from committed SFOE data, no keys needed
uv run pytest
```

Price data are never committed. To fetch them you need an ENTSO-E token in a
local `.env` (see `.env.example`). Data licences: [DATA_LICENCES.md](DATA_LICENCES.md).

Storage data: Source: Swiss Federal Office of Energy SFOE.
