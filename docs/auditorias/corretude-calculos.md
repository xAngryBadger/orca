# Auditoria de Corretude — Cálculos do Scheduler Orca

**Data:** 2026-11-06  
**Branch:** rework  
**Escopo:** `src/atm/orca/` — scheduler_core.py, tarifas.py, comparativo_real.py, engine_pkg/engine.py, bridge.py, config.py

---

## Sumário Executivo

| Item | Veredito | Resumo |
|------|----------|--------|
| 1. capacidade_dia_hh | ✅ **CORRETO** | `executores * jornada` |
| 2. Loop dia-a-dia (dedup, residual, parada, max) | ✅ **CORRETO** | Lógica sólida com `_HH_EPSILON=0.01` |
| 3. Resolução tarifa (HH vs HM, regra "HH zera HM") | ✅ **CORRETO** | Aplicada em 3 pontos |
| 4. Métricas (dias, meses, uso%, pendente, aprovação) | ✅ **CORRETO** | Fórmulas consistentes |
| 5. bridge._construir_demanda vs CLI | ⚠️ **SUSPEITO** | **Divergem**: bridge usa `area/rendimento_hm`; CLI usa `area*rendimento_hh` |
| 6. Divisão por zero (dias=0 ou capacidade=0) | ✅ **CORRETO** | Guarda existe em `comparativo_real.py:102` |

---

## 1. `capacidade_dia_hh = executores * jornada` — **CORRETO**

**Arquivo:** `src/atm/orca/comparativo_real.py:101`

```python
capacidade_dia = float(executores) * float(jornada)
```

- Fórmula direta, sem arredondamento intermediário
- Usada consistentemente em `uso_capacidade_pct` (linha 102)
- Consistente com o scheduler real (`engine.py:419`: `cap_dia = n_ops * config.jornada`)

---

## 2. Loop Dia-a-Dia do Scheduler — **CORRETO**

### 2.1 Deduplicação de Demanda
**Arquivo:** `src/atm/orca/engine_pkg/engine.py:310`
```python
demanda_global = config.demanda_global.copy()
```
- Cria cópia isolada — evita mutação do input original
- Chave composta `(talhao, atividade)` garante unicidade

### 2.2 HH Residual
**Arquivo:** `src/atm/orca/engine_pkg/engine.py:435-437`
```python
consumo = min(rest, cap_dia)
demanda_global[key] -= consumo
```
- Consome o mínimo entre demanda restante e capacidade do dia
- `cap_dia` = operários da turma × jornada

### 2.3 Condição de Parada (Demanda Zerada)
**Arquivo:** `src/atm/orca/engine_pkg/engine.py:331-334`
```python
tem_trabalho = any(v > _HH_EPSILON for v in demanda_global.values())
if not tem_trabalho:
    break
```
- `_HH_EPSILON = 0.01` (linha 155) — tolerância numérica adequada
- Para quando **todas** demandas ≤ 0.01 HH

### 2.4 Máximo de Dias
**Arquivo:** `src/atm/orca/engine_pkg/engine.py:314`
```python
MAX_DIAS = 10000
```
- Hard limit seguro (≈ 27 anos úteis)
- Loop `while dia < MAX_DIAS` (linha 331)

---

## 3. Resolução de Tarifa — **CORRETO**

### Regra: "Quando HH existe, HM é zerado"
Aplicada em **3 pontos** do código:

| Local | Arquivo:Linha | Contexto |
|-------|---------------|----------|
| 1 | `tarifas.py:353-354` | `_carregar_mapa_preco_final_json`: `if hh > 0: hm = 0.0` |
| 2 | `tarifas.py:412-413` | `_aplicar_mapa_preco_final_em_rows_by_name`: mesmo tratamento |
| 3 | `tarifas.py:467-471` | Validação final: `if rendimento_hh > 0 and rendimento_hm > 0: rendimento_hm = 0.0` |

### Rendimento HH vs HM
- `resolver_rendimento_hh` (linhas 62-108): retorna float ≥ 0, fallback para mediana/8.0
- `resolver_rendimento_hm` (linhas 110-134): retorna float ≥ 0, fallback 0.0
- **HM-only** (mecanizado): `rendimento_hh = 0.0`, `rendimento_hm > 0` — detectado em `engine.py:244-246`

---

## 4. Métricas — **CORRETO**

**Arquivo:** `src/atm/orca/comparativo_real.py:99-115`

```python
total_hh = sum(v for v in demanda.values())
pendente = sum(v for v in demanda_restante.values() if v > 0.01)
capacidade_dia = float(executores) * float(jornada)
uso_pct = (100.0 * total_hh / (dias * capacidade_dia)) if dias > 0 and capacidade_dia > 0 else 0.0

return {
    "dias_simulados": int(dias),
    "meses_simulados": round(dias / 22.0, 2),
    "hh_total": round(total_hh, 2),
    "hh_pendente": round(pendente, 2),
    "capacidade_dia_hh": round(capacidade_dia, 2),
    "uso_capacidade_pct": round(uso_pct, 1),
    "aprovacao": "COMPLETO" if pendente <= 0.01 else "INCOMPLETO",
}
```

| Métrica | Fórmula | Veredito |
|---------|---------|----------|
| `dias_simulados` | `int(dias)` do loop | ✅ |
| `meses_simulados` | `dias / 22.0` | ✅ (constante `DIAS_UTEIS_POR_MES=22.0`) |
| `uso_capacidade_pct` | `100 * hh_total / (dias * capacidade_dia)` | ✅ |
| `hh_pendente` | Soma `demanda_restante > 0.01` | ✅ |
| `aprovacao` | `COMPLETO` se `pendente <= 0.01` | ✅ |

---

## 5. `bridge._construir_demanda` vs CLI — **SUSPEITO (DIVERGEM)**

### Bridge (Painel Web) — `src/atm/web/bridge.py:184-200`
```python
def _construir_demanda(micro_rows, tarifas):
    demanda = {}
    for row in micro_rows:
        talhao = row.chave
        atividade = row.atividade
        area = float(row.area_ha)
        tarifa = tarifas.get(atividade, {})
        rendimento_hm = tarifa.get("rendimento_hm", 0.0)
        if rendimento_hm and rendimento_hm > 0:
            hh = area / rendimento_hm          # ← DIVISÃO
        else:
            rendimento_hh = tarifa.get("rendimento_hh", 0.0)
            hh = area * rendimento_hh if rendimento_hh else area  # ← MULTIPLICAÇÃO (fallback area)
        demanda[(talhao, atividade)] = round(hh, 2)
```

### CLI (Scheduler Real) — `src/atm/orca/engine_pkg/engine.py:234`
```python
horas = area * rend_hh_ha  # rend_hh_ha = rendimento_hh * penalidade
```

### Diferenças Críticas

| Aspecto | Bridge (Web) | CLI (Scheduler) | Impacto |
|---------|--------------|-----------------|---------|
| **HM → HH** | `area / rendimento_hm` | **Não existe** — HM roda em paralelo, não vira HH | Bridge superestima HH se HM>0 |
| **HH direto** | `area * rendimento_hh` | `area * rendimento_hh * penalidade` | Bridge **ignora penalidade** |
| **Fallback** | `area` (1 HH/ha) | Mediana/8.0 via `resolver_rendimento_hh` | Bridge subestima se tarifa zerada |
| **Chave tarifa** | `atividade` direto | `resolver_chave_tarifa(cfg, tarifas, atv)` (de_para) | Bridge ignora mapeamento de_para |

### Cenário que Quebra
> **Micro com atividade "Plantio" que tem `rendimento_hm=0.5` (2 ha/dia) e `rendimento_hh=0`.**  
> Bridge calcula `hh = area / 0.5 = 2*area` → insere HH fake no scheduler humano.  
> Scheduler real trata como **mecanizado (HM-only)** → fila paralela, não consome HH da equipe.

**Evidência:** `engine.py:244-246` detecta `is_mec = hm_ha > 0 and rend_hh_ha <= 0` e adiciona a `hm_only_atividades`.

---

## 6. Divisão por Zero — **CORRETO (Guarda Existe)**

**Arquivo:** `src/atm/orca/comparativo_real.py:102`
```python
uso_pct = (100.0 * total_hh / (dias * capacidade_dia)) if dias > 0 and capacidade_dia > 0 else 0.0
```

- Guarda dupla: `dias > 0` **E** `capacidade_dia > 0`
- `capacidade_dia = executores * jornada` — só é 0 se `executores=0` ou `jornada=0`
- `dias` só é 0 se loop não rodou (demanda já zerada no início)

---

## Achados Mais Importantes

1. **`bridge.py:184-200`** — `_construir_demanda` **diverge do CLI**: usa `area/rendimento_hm` (errado para HM-only), ignora `penalidade`, ignora `de_para`, fallback `area` (1 HH/ha) vs mediana/8.0.

2. **`tarifas.py:353-354, 412-413, 467-471`** — Regra "HH zera HM" aplicada corretamente em 3 pontos, mas **bridge não respeita**: trata HM como se virasse HH.

3. **`comparativo_real.py:102`** — Guarda contra divisão por zero existe e está correta (`dias > 0 and capacidade_dia > 0`).