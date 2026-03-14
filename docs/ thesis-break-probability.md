**Short answer:**
Add a **Thesis Break Probability (TBP)** layer that estimates the probability the **core thesis becomes invalid**, independent of valuation.

This improves **position sizing and risk control** dramatically.

---

# What Thesis Break Probability Is

Your system currently estimates:

```text
Probability the investment works
```

But professional investors also estimate:

```text
Probability the thesis becomes invalid
```

These are **not the same**.

Example:

| Scenario          | Investment works | Thesis breaks |
| ----------------- | ---------------- | ------------- |
| Company stagnates | ❌                | ❌             |
| Company improves  | ✅                | ❌             |
| Company collapses | ❌                | ✅             |

So TBP captures **structural failure risk**.

---

# Where It Fits in Your System

Add it **after the epistemic review**.

Pipeline becomes:

```text
Analyst
   ↓
Validator
   ↓
Epistemic Reviewer (PCS)
   ↓
Thesis Break Analyzer
   ↓
Position Sizing
```

---

# What TBP Measures

The agent asks:

**“What events would make this thesis invalid?”**

Example output:

```json
{
 "thesis_break_events": [
   {
     "event": "Permanent regulatory restriction on core business",
     "probability": 0.15
   },
   {
     "event": "Structural loss of competitive moat",
     "probability": 0.10
   },
   {
     "event": "Liquidity crisis / refinancing failure",
     "probability": 0.08
   }
 ]
}
```

Then:

```text
Thesis Break Probability = combined probability of events
```

---

# Simple Aggregation

Use capped additive risk:

```python
TBP = min(sum(event_probabilities), 0.6)
```

Example:

```text
0.15 + 0.10 + 0.08 = 0.33
```

TBP = **33%**

---

# How It Improves Position Sizing

Current logic likely resembles:

```text
Position size ∝ probability × expected return
```

With TBP:

```text
Position size ∝ probability × expected return × (1 − TBP)
```

Example:

| Metric              | Value |
| ------------------- | ----- |
| Success probability | 60%   |
| Expected return     | 2.5x  |
| TBP                 | 30%   |

Adjusted sizing factor:

```text
0.60 × 2.5 × (1 − 0.30)
= 1.05
```

Without TBP it would be:

```text
0.60 × 2.5 = 1.50
```

Position shrinks **30%**.

---

# Why This Matters

Two investments can have identical probabilities but **very different fragility**.

Example:

| Company            | Success Prob | TBP |
| ------------------ | ------------ | --- |
| Turnaround         | 60%          | 40% |
| Quality compounder | 60%          | 10% |

Your system should size these **very differently**.

TBP captures **structural fragility**.

---

# Questions the TBP Agent Should Ask

1️⃣ **Single Point of Failure**

```text
Does the thesis depend on one critical assumption?
```

2️⃣ **Capital Structure Risk**

```text
Could financing failure break the thesis?
```

3️⃣ **Regulatory Regime Risk**

```text
Could regulation permanently impair the business model?
```

4️⃣ **Technological Disruption**

```text
Could a superior technology invalidate the moat?
```

5️⃣ **Market Structure Change**

```text
Could industry dynamics structurally change?
```

---

# TBP Scoring Framework

| Break Risk Level | TBP    |
| ---------------- | ------ |
| Minimal          | 5-10%  |
| Low              | 10-20% |
| Moderate         | 20-35% |
| High             | 35-50% |
| Extreme          | 50-60% |

Cap TBP at **60%** to avoid runaway pessimism.

---

# Architecture Example

Add one file:

```text
analysis/
 ├── thesis_break_analyzer.py
```

---

# TBP Agent Output Example

```json
{
 "tbp": 0.28,
 "break_events": [
   "Regulatory restrictions on market expansion",
   "Loss of key supplier relationships",
   "Debt covenant breach risk"
 ]
}
```

---

# Final Probability Framework

Your final probability pipeline becomes:

```text
Posterior Probability
    ↓
PCS Multiplier
    ↓
Effective Probability
    ↓
Position Size Adjustment
    × (1 − TBP)
```

---

# Why This Is Powerful

Most AI investment systems miss **fragility analysis**.

Your pipeline would then contain:

1. Analyst reasoning
2. Validator challenge
3. Blind epistemic review
4. Evidence calibration
5. **Thesis break detection**
6. Probability adjustment
7. Position sizing

That is very close to **institutional investment committee logic**.

---

If you want, I can also show you one **final improvement that would make this system extremely robust**:

**“Narrative Stress Testing”**

It prevents LLMs from producing **beautiful but fragile theses**.
