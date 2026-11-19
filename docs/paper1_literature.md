# Paper 1 — Literature review (first pass)

**Date:** 2026-11-17. **Closes:** research-plan v2 checklist item 3 and the
"literature review" line of Paper 1's P0. **Decision log:** row 50.

**Method and its limits.**
- 20 targeted web searches on 2026-11-17.
- Bibliographic details were confirmed from RePEc/IDEAS, the publisher or
  NBER pages. **Findings are from abstracts and metadata, not full texts.**
- The column "Checked" says what was confirmed. Full-text reading of the core
  papers (marked ★) is still to do before drafting.
- A search that finds nothing is not proof that nothing exists. The gap claims
  in §2 must be re-checked with Google Scholar forward citations (§5).

---

## 1. The literature, by strand

### A. Forecast rationality, revisions and loss functions

| | Reference | What it does | Use in Paper 1 | Checked |
|---|---|---|---|---|
| ★ | Mincer & Zarnowitz (1969), "The Evaluation of Economic Forecasts", in Mincer (ed.), *Economic Forecasts and Expectations*, NBER, pp. 3–46 | Efficiency regression of outcome on forecast | C1's S1–S8 tests | NBER chapter page |
| ★ | Nordhaus (1987), "Forecasting Efficiency: Concepts and Applications", *Review of Economics and Statistics* 69(4), 667–674 | Weak efficiency for fixed-event forecasts: revisions should be uncorrelated. Tests macro, **energy-consumption** and oil-price forecasts; 50 of 51 tests show positive revision autocorrelation (smoothing). | Direct precedent for C1's revision tests on an energy forecast. C1's per-pair slopes (positive late in the gas day) are a Nordhaus-type smoothing result. | RePEc |
| ★ | Coibion & Gorodnichenko (2015), "Information Rigidity and the Expectations Formation Process", *American Economic Review* (NBER WP 16537, 2010) | Regress ex-post error (actual − forecast) on the ex-ante revision; the slope measures information rigidity. Positive slope = under-reaction. | The standard modern framing of C1's primary test; reviewers will expect it. | NBER WP; AER volume and pages **not confirmed from a primary source** |
| ★ | Bordalo, Gennaioli, Ma & Shleifer (2020), "Overreaction in Macroeconomic Expectations", *AER* 110(9), 2748–2782 | Coibion–Gorodnichenko (CG) regressions: individual forecasters over-react, consensus forecasts under-react | Interprets the sign of the revision slope for a *single institutional* forecaster | RePEc |
| ★ | Elliott, Komunjer & Timmermann (2005), "Estimation and Testing of Forecast Rationality under Flexible Loss", *Review of Economic Studies* 72(4), 1107–1125 | GMM estimate of a loss-asymmetry parameter; rationality tests given it | H3 | RePEc |
| | Elliott, Komunjer & Timmermann (2008), "Biases in Macroeconomic Forecasts: Irrationality or Asymmetric Loss?", *JEEA* 6(1), 122–157 | Standard rationality tests are not robust to small loss asymmetries | Why C1's rejections need not mean irrationality | RePEc |
| ★ | Patton & Timmermann (2007), "Testing Forecast Optimality under Unknown Loss", *JASA* 102(480), 1172–1184 | Loss may depend on **state variables**, not just the error. The Fed's forecasts are rational only if over-prediction is costlier in low-growth states. | Natural model for a cold-day over-forecast: security-of-supply loss that depends on demand level (see §3.2) | Duke listing |
| | Elliott & Timmermann (2008), "Economic Forecasting", *Journal of Economic Literature* 46(1), 3–56 | Survey of forecast evaluation and comparison | Background citation | RePEc |
| | Harvey, Leybourne & Newbold (1998), "Tests for Forecast Encompassing", *JBES* 16(2), 254–259 | Encompassing tests robust to non-normal errors | H4 | RePEc |
| | Diebold & Mariano (1995), "Comparing Predictive Accuracy", *JBES* 13(3), 253–263 | Equal-accuracy test | Already used in C1 | **Not searched; from memory, verify** |

### B. Operator (TSO) energy-demand forecasts

| | Reference | What it does | Use in Paper 1 | Checked |
|---|---|---|---|---|
| ★ | Thomas, Massol & Sévi (2022), "How are Day-ahead Prices Informative for Predicting the Next Day's Consumption of Natural Gas? Evidence from France", *The Energy Journal* 43(5) | Long-run relation between daily French gas demand and day-ahead prices; models with price information beat the network operators' published forecasts | **Closest paper.** H4 is its GB counterpart; Paper 1 adds intraday publications and the incentive. | RePEc, IAEE |
| ★ | Möbius, Watermeyer, Grothe & Müsgens (2023), "Enhancing Energy System Models Using Better Load Forecasts", *Energy Systems* (arXiv 2302.11017) | German TSO day-ahead load forecasts on ENTSO-E are biased and autocorrelated. A simple real-time correction cuts MSE 26%, and price-model MSE by ~15% in high-price hours. | Contrast with C1: the GB gas operator's bias is not exploitable by a comparable correction, because it is non-stationary | Springer, arXiv |
| | Kazmi & Tao (2022), "How good are TSO load and renewable generation forecasts", *Applied Energy* 323, 119565 | Five years of TSO load/wind/solar forecasts in 16 European countries; room for improvement | Electricity benchmark for operator forecast quality | RePEc |
| | Soldo (2012), "Forecasting natural gas consumption", *Applied Energy* 92, 26–37; Tamba et al. (2018), *IJEEP* 8(3), 216–249 | Surveys of gas demand forecasting methods | Background. These cover *building* forecasts, not *evaluating* an operator's published forecast. | RePEc |

### C. Public news and energy prices

| | Reference | What it does | Use in Paper 1 | Checked |
|---|---|---|---|---|
| ★ | Linn & Zhu (2004), "Natural Gas Prices and the Gas Storage Report", *Journal of Futures Markets* 24(3), 283–313 | Intraday NYMEX gas volatility around the weekly storage report | The canonical gas "public-news" event study. H1 is its analogue with an operator *demand* publication. | RePEc |
| ★ | Halova, Kurov & Kucher (2014), "Noisy Inventory Announcements and Energy Prices", *JFM* 34(10), 911–933 | Measurement error in the measured surprise biases price responses towards zero; corrected effects are larger | **Design implication for H1:** a raw revision is a noisy proxy for news, so expect attenuation (§3.3) | RePEc |
| | Mu (2007), "Weather, Storage, and Natural Gas Price Dynamics", *Energy Economics* 29(1), 46–63 | Weather shocks move the mean and volatility of US gas futures returns | Weather news as a control in H1 | RePEc |
| | Kiesel & Paraschiv (2017), "Econometric analysis of 15-minute intraday electricity prices", *Energy Economics* 64, 77–90 | German intraday prices respond **asymmetrically** to wind/solar forecast updates, with a threshold in a demand-tightness measure | Precedent for state-dependent price response to forecast updates (§3.4) | RePEc |
| | Schönheit, Homann, Möst & Westgaard (2022), "Measuring the effect of corrective short-term updates for wind energy forecasts on intraday electricity prices", *Journal of Energy Markets* | Wind forecast updates move intraday prices; the effect is larger at high residual load (steeper merit order) | Same | RePEc |
| | Kulakov & Ziel (2021), "The impact of renewable energy forecasts on intraday electricity prices", *Economics of Energy & Environmental Policy* (arXiv 1903.09641) | Non-linear price impact of renewable forecast errors | Same | RePEc |

### D. The 2022/23 demand response

| Reference | What it does | Use | Checked |
|---|---|---|---|
| Ruhnau, Stiewe, Muessel & Hirth (2023), "Natural gas savings in Germany during the 2022 energy crisis", *Nature Energy* 8, 621–628 | Weather-adjusted counterfactual; German gas consumption down ~23% in H2 2022 (press release); code public | Method template for C's demand-response counterfactual | RePEc, Nature |
| OBR (box), "How gas demand and supply have responded to higher gas prices" | GB household demand ~15% lower, weather-adjusted, winter 2022/23; elasticity ~ −0.1 | Magnitude C compares against | OBR page |
| Warwick CAGE WP 727 (2024) | GB household gas reduction ~13% | Same | Warwick page |

### E. Institutions (primary documents)

| Document | Content | Use |
|---|---|---|
| National Gas, demand-forecasting incentive page; *Incentive Performance Supporting Information 2024/25* | 13:00 D−1 forecast; annual weighted-average absolute error; RIIO-2 target 8.35 mcm/d (+ storage adjuster), ±£1.5m; current page 6.79 mcm/d, ±£1.7m | H2–H3 loss function |
| Licence Special Condition 5.6 Part C (from 2022-11-01; earlier SpC 3D) | The formula itself | **To obtain**, for the weights |
| UNC Modification 0461; EU CAM network code | Gas day 05:00 UTC in winter, 04:00 UTC in summer | Decision log row 49 |
| Ofgem SO-incentive decisions (2006 onward); Ofgem forecast-symmetry consultation | History of the incentive, including a proposed symmetry incentive | Institutional background section |

---

## 2. The gap (provisional, pending §5 checks)

None of the searches found:

1. **A revision-efficiency or CG test of a TSO's energy-demand forecast using
   its full intraday publication history.** Nordhaus (1987) tested energy
   forecasts, but low-frequency macro ones. The TSO studies (Möbius et al.,
   Kazmi & Tao) evaluate one publication per day, for electricity.
2. **A rationality test under a loss function written into regulation.** The
   asymmetric-loss literature estimates the loss because it is unknown. Here a
   licence specifies it (absolute error, annual average), which turns
   Elliott–Komunjer–Timmermann (EKT) / Patton–Timmermann from estimation into
   a test with a known loss.
3. **A GB counterpart of Thomas, Massol & Sévi (2022)**, or any study of
   whether NBP prices contain demand information beyond the operator's
   forecast.
4. **A news-impounding study of operator gas-demand publications.** The
   analogues are US storage reports (Linn & Zhu; Halova et al.) and
   renewable-forecast updates in power markets (Kiesel & Paraschiv; Schönheit
   et al.; Kulakov & Ziel). No gas-demand-forecast analogue was found.
5. **How fast an operational demand forecast adapted to the 2022/23
   price-driven demand fall.** The demand-response papers measure the fall,
   not the forecaster's learning.

Points 1–2 support an IJF-style framing. Points 3–4 support The Energy
Journal, and 5 is a short exploratory section.

---

## 3. Design implications, **proposed** for the pre-registration (not yet frozen)

### 3.1 Report the primary revision test in the Coibion–Gorodnichenko sign convention
- C1 regressed (forecast − actual) on the revision; CG regress (actual −
  forecast).
- **In CG convention C1's slope is +0.044**: mild under-reaction, not
  significant (95% CI ≈ [−0.20, 0.29]).
- The paper reports both conventions, so readers of Bordalo et al. can place
  a single institutional forecaster against the consensus-under-reacts
  benchmark.
- This changes labelling only; no re-estimate.

### 3.2 State-dependent loss for H3
- Patton & Timmermann (2007) let the loss depend on the state. A
  security-of-supply operator plausibly dislikes under-forecasting more on cold
  days.
- **Proposal:** H3 estimates the EKT asymmetry α separately for the
  cold-regime and other days.
- Because the cold-regime split was suggested by C0/C1 (S11), this extension
  is scored on the **confirmation sample only**, alongside H7.

### 3.3 Expect, and say we expect, attenuation in H1
- Halova et al. (2014) show that a noisy surprise measure biases price
  responses towards zero.
- The raw NTS revision is the operator's update, not the market's surprise:
  part of it is predictable from public weather-forecast changes.
- **Proposal:**
  - keep the weather-news control;
  - pre-register a second H1 specification that uses only the part of
    `R_post` orthogonal to public weather news;
  - state before estimation that a null on the raw revision does not rule out
    a smaller true effect, and that the MDE reflects this.

### 3.4 One pre-registered state interaction for H1
- Kiesel & Paraschiv (2017) and Schönheit et al. (2022) find price responses
  to forecast updates are larger when the system is tight.
- **Proposal:** a single interaction of `R_post` with a tightness proxy fixed
  in advance (cold regime, or a predicted closing linepack below its seasonal
  median), labelled secondary.
- One interaction only, to keep the test family small.

### 3.5 Replicate Thomas et al.'s specification as a named baseline for H4
- Their long-run demand–price relation, re-estimated on GB, is the
  "published-method" baseline.
- Without it a referee will ask why their specification was not used.

### 3.6 Framing against the electricity TSO studies
- Möbius et al. find German load-forecast bias is exploitable by a simple
  correction. C1 finds the GB gas operator's bias is **not** exploitable
  out of sample, because it is non-stationary.
- That contrast belongs in the introduction. It is a C1 result already
  obtained, not a new test.

---

## 4. Venue implications

- **The Energy Journal:** cite Thomas–Massol–Sévi prominently and position
  Paper 1 as the GB, multi-publication sequel. Lead with points 3–4 of §2.
  Ruhnau et al. and OBR anchor C.
- **IJF** (if A becomes the headline): lead with points 1–2 of §2. Present
  the CG + EKT/Patton–Timmermann framing with the regulator-defined loss as
  the methodological novelty.

---

## 5. Still to do before drafting

1. Read the ★ papers in full, especially Thomas et al. (exact specification,
   sample, which operator forecast and publication time) and Halova et al.
   (the attenuation correction).
2. Google Scholar **forward citations** of Thomas et al. (2022), Nordhaus
   (1987, energy applications) and Linn & Zhu (2004), restricted to gas or
   TSO, to re-check gaps 1, 3 and 4.
3. Search for NBP-specific market-efficiency and weather-news studies. None
   was found in this pass, which is surprising and must be re-checked.
4. Obtain licence SpC 5.6 Part C and its RIGs table (incentive weights).
5. Verify the AER volume and pages for Coibion & Gorodnichenko (2015) and the
   Diebold–Mariano reference.

---

## Sources (searched 2026-11-17)

- Mincer & Zarnowitz: https://www.nber.org/chapters/c1214.pdf
- Nordhaus 1987: https://ideas.repec.org/a/tpr/restat/v69y1987i4p667-74.html
- Coibion & Gorodnichenko: https://www.nber.org/papers/w16537.pdf
- Bordalo et al. 2020: https://econpapers.repec.org/RePEc:aea:aecrev:v:110:y:2020:i:9:p:2748-82
- EKT 2005: https://econpapers.repec.org/RePEc:oup:restud:v:72:y:2005:i:4:p:1107-1125
- EKT 2008: https://econpapers.repec.org/RePEc:tpr:jeurec:v:6:y:2008:i:1:p:122-157
- Patton & Timmermann 2007: https://scholars.duke.edu/publication/792439
- Elliott & Timmermann 2008: https://econpapers.repec.org/RePEc:aea:jeclit:v:46:y:2008:i:1:p:3-56
- Harvey, Leybourne & Newbold 1998: https://ideas.repec.org/a/bes/jnlbes/v16y1998i2p254-59.html
- Thomas, Massol & Sévi 2022: https://ideas.repec.org/a/aen/journl/ej43-5-massol.html
- Möbius et al. 2023: https://link.springer.com/article/10.1007/s12667-023-00590-3
- Kazmi & Tao 2022: https://ideas.repec.org/a/eee/appene/v323y2022ics0306261922008753.html
- Soldo 2012: https://econpapers.repec.org/RePEc:eee:appene:v:92:y:2012:i:c:p:26-37
- Linn & Zhu 2004: https://ideas.repec.org/a/wly/jfutmk/v24y2004i3p283-313.html
- Halova, Kurov & Kucher 2014: https://ideas.repec.org/a/wly/jfutmk/v34y2014i10p911-933.html
- Mu 2007: https://ideas.repec.org/a/eee/eneeco/v29y2007i1p46-63.html
- Kiesel & Paraschiv 2017: https://econpapers.repec.org/RePEc:eee:eneeco:v:64:y:2017:i:c:p:77-90
- Schönheit et al. 2022: https://ideas.repec.org/a/rsk/journ2/7955013.html
- Kulakov & Ziel: https://econpapers.repec.org/paper/arxpapers/1903.09641.htm
- Ruhnau et al. 2023: https://ideas.repec.org/a/nat/natene/v8y2023i6d10.1038_s41560-023-01260-5.html
- OBR: https://obr.uk/box/how-gas-demand-and-supply-have-responded-to-higher-gas-prices/
- Warwick CAGE WP 727: https://warwick.ac.uk/fac/soc/economics/research/centres/cage/manage/publications/wp727.2024.pdf
- National Gas incentive: https://nationalgas.com/about-us/system-operator-incentives/demand-forecasting
- UNC 0461: https://gasgovernance.co.uk/sites/default/files/archive/modes/0451-0475/0461%20-%20Changing%20the%20UNC%20Gas%20Day%20to%20Align%20with%20the%20Gas%20Day%20in%20EU%20Network%20Codes/Final%20Modification%20Report%200461%20v2.0.pdf
