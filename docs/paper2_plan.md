# Paper 2 plan — Building stock and the temperature sensitivity of LV electricity demand

**Date:** 2026-11-17. **Status:** plan only; no feeder data has been pulled.
**Relation to Project A:** this tests Project A's claim 1 (stock explains
demand) at a scale where it is identifiable. Phase 1b failed with 12 usable gas
zones. It does **not** test claims 2–3 (information beyond the NESO forecast,
tradeability), and the paper must not say it does. It will probably need its
own repository once data work starts. This plan lives here for now.

---

## 0. Venue

| Venue | Role | Why |
|---|---|---|
| **Applied Energy** | **Primary** | Publishes smart-meter, building-stock and network-planning work at volume. It values scale, open data, a clear application and comparison with field-trial magnitudes, all of which this design supplies. |
| ACM e-Energy | Alternative, **not as well** | Archival proceedings would overlap with a journal version. Choose it only if a method contribution is added (§8). 2026's deadline was 22 Jan 2026; 2027 not confirmed. |

**Applied Energy practicalities:**
- **highlights:** 3–5 bullets, each under 85 characters;
- **graphical abstract:** prepare one;
- **data and code availability statement;**
- **word and abstract limits:** third-party sources disagree (8,000 vs 12,000
  words; 200 vs 250 for the abstract). Confirm from the Elsevier guide for
  authors before drafting.

---

## 1. What the paper claims

As with Paper 1, every claim is publishable under either outcome.

1. **Scale.** Temperature-response estimates for about 100,000 GB LV feeders
   (about 2 million smart meters, 4 DNOs) from open data, released as a
   reusable dataset with a DOI. Scale and openness are what Applied Energy
   rewards, and the dataset outlives the paper.
2. **Does EPC stock data add information beyond the Census?** Census 2021
   central-heating type is free, complete and has no selection bias. The
   question is whether EPC fabric and heating-system data explain feeder
   temperature sensitivity *beyond* it, out of sample.
   - *Yes* → stock data matters for network planning.
   - *No* → planners can use the Census, and EPC fabric data does not help.
     DNOs would use that negative directly.
   - This keeps Project A's "incremental information" logic, with a better
     baseline.
3. **Does fabric matter, given the heating fuel?** The fabric effect on the
   heating slope, conditional on heating fuel and socio-demographics,
   estimated by double machine learning (DML).
   - Includes an omitted-variable sensitivity bound (Cinelli–Hazlett robustness
     value).
   - Framed as a conditional association with a stated robustness value, not
     a causal effect, unless the bound is strong.
4. **Application.** Winter-peak uplift by feeder under heat-pump uptake
   scenarios, and the share of feeders that would exceed a headroom proxy.
   Applied Energy referees look for a use.

**The trap to avoid.** About 85% of GB homes heat with gas. Feeder temperature
sensitivity will be dominated by the share of electrically heated homes and
heat pumps. "Electric-heated feeders are more temperature-sensitive" is
trivially true and would be desk-rejected as the headline. Contributions 2 and
3 are framed around what remains **after** heating fuel is controlled for.

---

## 2. Data

| Series | Source | Licence | Audit task |
|---|---|---|---|
| **Feeder half-hourly consumption** (aggregate) | Weave Half Hourly Energy Consumption (GeoParquet; 4 DNOs; ~100k feeders; ~2M meters), on the SSEN data portal | per DNO | Which DNOs, history start, meter counts per feeder over time, the gap-filling Weave did ("filled in a couple of blanks"). **Prefer the raw DNO files if the fills can't be identified.** |
| SSEN Smart Meter LV Feeder Usage | SSEN data portal | CC-BY-4.0 | ≥5 properties per aggregate; UTC timestamps; Output Area mapping in the pipeline version; substation location in a separate dataset |
| NGED smart meter LV feeder data | NGED portal; LSOA-linked derived copy on SDRUK | NGED Shared Data Licence (confirm) | Linkage method of the derived copy; rebuild the join if it is not documented |
| UKPN smart meter consumption, LV feeder | Open Net Zero / UKPN | confirm | Same checks |
| **EPC England & Wales** | on disk (88 GB, `heat_nowcast.data.epc`) | OGL except address fields | As-of construction per winter (§3) |
| Scottish EPC | Scottish EPC register | separate | Needed for SSEN north. Otherwise restrict to England & Wales and say so. |
| **Census 2021** | Nomis | OGL | Central heating type (TS046), accommodation type, tenure, household size, at OA or LSOA |
| Deprivation | IMD 2019 (England), WIMD (Wales) | OGL | — |
| Low-carbon technologies | MCS installations (heat pumps, PV); DfT plug-in vehicles by LSOA (VEH0135 or successor) | confirm | Granularity and dating |
| **Weather** | HadUK-Grid 1 km daily; ERA5-Land hourly for peak hours | OGL / Copernicus | **Realised weather is the correct input here.** The estimand is a physical response, not a forecast or trading signal, so `CLAUDE.md` §2.1 does not bar it. Still use the `_realised` suffix and state it in the paper. |
| Network headroom | DNO network development plans / substation headroom data | per DNO | For the application only |

---

## 3. Point-in-time and measurement rules

This is not a forecasting study, but three timing leaks still apply.

1. **EPC as-of each winter.** Use the latest EPC lodged *before* the winter
   being explained. An EPC lodged in 2025 that records a new heat pump must
   not explain 2024/25 demand.
2. **Meter-count drift.**
   - The smart-meter rollout changes a feeder's composition during the sample.
   - Normalise to kWh per meter.
   - Drop feeders whose meter count changes by more than a threshold set
     before estimation.
3. **UTC throughout.** BST transition days are handled, not dropped silently.

**Ecological inference.**
- The estimand is feeder-level, and conclusions about individual dwellings
  are not drawn.
- Feeder → OA/LSOA links are many-to-many. Weight stock features by meter or
  postcode overlap, and report results restricted to feeders whose link is
  one-to-one.

---

## 4. Design

**Stage 1 — per-feeder temperature response.** For each feeder and winter:

`kWh_per_meter_day = base + slope · max(0, T_b − T_realised) + day-of-week + holiday + ε`

- T_b is estimated per feeder over a grid.
- Repeat for the 16:00–19:00 evening-peak half-hours.
- Keep the standard errors.

**Kill K2:** if most feeders' slopes are indistinguishable from zero (median
|t| < 2), aggregate to secondary substations before going further.

**Stage 2 — explain the slopes** (baselines first, each a named model with
tests):

| Model | Features |
|---|---|
| B0 | DNO / region fixed effects + local climate |
| **B1 (strong baseline)** | B0 + Census 2021 central-heating-type shares |
| B2 | B1 + accommodation type, tenure, household size, deprivation, PV/EV/heat-pump density |
| **M** | B2 + EPC stock features: heating system and fuel, wall, roof and glazing efficiency, SAP score, floor area, age band. Reweighted for EPC coverage against Census dwelling counts. |

- **Primary metric:** out-of-sample ΔR² (M − B2) of the heating slope, with a
  bootstrap CI clustered on spatial blocks.
- Fitted with a linear model (interpretable) and gradient boosting (flexible),
  both reported.
- Stage-1 SEs enter as inverse-variance weights; attenuation from measurement
  error is checked.

**Splits** (never random, never k-fold):
- **Spatial transfer:** leave one DNO out. This is the network-planning use
  case: does a model fitted elsewhere work on a new network?
- **Temporal:** fit on winter 2024/25, score on winter 2025/26 (or the latest
  complete winter, depending on history start).
- Spatial blocking matters because neighbouring feeders share weather and
  housing. A random split would inflate R².

**Stage 3 — fabric effect given heating fuel.**
- DML partially-linear model: θ = effect of a fabric-efficiency index on the
  heating slope, with B2 features as controls.
- Estimated in strata of electric-heating share.
- Causal forest for heterogeneity (EconML).
- Cinelli–Hazlett robustness value reported.

**Stage 4 — application.**
- Peak uplift per added heat pump = the heat-pump slope from stage 2/3 × the
  temperature gap on a design cold day.
- Check the per-heat-pump figure against field-trial magnitudes
  (Electrification of Heat demonstration; RHPP) before using it.
- Uptake scenarios from public pathway documents.
- Output: share of feeders exceeding a headroom proxy.

---

## 5. Kill criteria and pre-registration

Freeze these in the decision log before stage 2 sees the holdout data.

| ID | Criterion | If it fires |
|---|---|---|
| K1 | Feeder → geography link covers < 70% of meters in a DNO | Drop that DNO from the primary analysis; report it separately |
| K2 | Median stage-1 slope |t| < 2 | Aggregate to secondary substations |
| K3 | ΔR² (M − B2) CI includes 0 under both splits | **Write up the negative:** the Census suffices. It is still the paper; contribution 2 flips sign. |

---

## 6. What Applied Energy referees will check

- **Magnitudes against the literature:** per-meter heating slopes and
  heat-pump peak contributions compared with field trials and SERL-based
  studies.
- **Uncertainty everywhere:** CIs on ΔR², θ and the application's exceedance
  share.
- **Limitations section:**
  - short history (two winters);
  - ecological inference;
  - EPC selection (coverage reweighting reported);
  - meter rollout drift;
  - DNO differences in aggregation.
- **Open data and code:** feeder-level slopes and code deposited on Zenodo, if
  the licences allow. **Check the NGED licence for redistributing derived
  data.**
- **Figures:**
  - a GB map of feeder slopes;
  - the ΔR² ladder B0 → M;
  - θ by electric-heating share;
  - the exceedance map.

---

## 7. Phases

| Phase | Work | Exit |
|---|---|---|
| P0 data audit (≈2 wk) | Pull Weave or raw DNO files; linkage quality; meter drift; history start; licences | K1 recorded; data inventory updated |
| P1 stage 1 (≈1–2 wk) | Feeder temperature responses with SEs | K2 recorded |
| P2 baselines and stage 2 (≈2 wk) | B0 → B2 first, then M; both splits | K3 recorded |
| P3 stage 3 and application (≈1–2 wk) | DML, robustness value, scenarios | — |
| P4 manuscript (≈2 wk) | Highlights, graphical abstract, data deposit | Submit to Applied Energy |

About 8–10 weeks in total. P0 is the long pole: the data is large and the
linkage quality is unknown.

---

## 8. If e-Energy instead

- An ACM-format short paper needs a **method** contribution. For example, a
  hierarchical model that pools slope estimates across feeders, so sparse
  feeders borrow strength, evaluated on leave-one-DNO-out transfer.
- Submit the dataset as an artifact.
- Do not submit an overlapping version to Applied Energy afterwards; choose
  one.

---

## 9. Manuscript outline (Applied Energy)

1. Introduction: heat electrification and LV network risk; the gap (no
   GB-scale evidence linking stock to feeder temperature response)
2. Data: feeder aggregates, linkage, EPC as-of, Census
3. Method: stage 1, the baseline ladder, DML, the splits
4. Results: slopes; the ΔR² ladder; fabric given fuel
5. Application: heat-pump uptake and feeder exceedance
6. Validation against field trials
7. Limitations
8. Conclusion and policy implications for DNO planning

Data and code availability statement; highlights; graphical abstract.
