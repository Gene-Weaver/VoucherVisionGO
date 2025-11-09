# VoucherVisionGO — Impact Methodology

> The estimates we calcualte may evolve with time. Cloud computing is not transparent about inference impacts and many factors can influence CO₂ emissions. We found this article to be insightful:  
> [Is Google’s Reveal of Gemini’s Impact Progress or Greenwashing?](https://towardsdatascience.com/is-googles-reveal-of-geminis-impact-progress-or-greenwashing/)

We provide multiple estimates of CO₂ emissions and energy usage. If you come across a more accurate way of estimating LLM inference impacts—specifically for **Google Cloud** infrastructure—we'd love to hear about it and incorporate it into these estimates.

Here we only include estimates for **Google Cloud** because that is the infrastructure powering the **VoucherVisionGO API**.

---

### Average token counts (typical herbarium specimen)
**OCR**
  - Input = 2,00* tokens  
  - Output = 500 tokens
  - Total = 2,500 tokens  

**LLM Parsing**
  - Input = 2,000 tokens  
  - Output = 500 tokens
  - Total = 2,500 tokens  

**Overall**
  - **Total = 5,000 tokens**

> For Notebook transcription the results vary significantly.

Additional notes:

- Water use is extremely complex and varies significantly by data center. We rely on Google’s estimate.
- We assume the “cost” of input and output tokens are equivalent, though “thinking” models may differ.

---

## Sources & Estimation Approaches

### `source_google`
- **Original:** [Google Cloud Blog — Measuring the Environmental Impact of AI Inference](https://cloud.google.com/blog/products/infrastructure/measuring-the-environmental-impact-of-ai-inference)
- **Archive:** [(Archive) Google Cloud Blog — Measuring the Environmental Impact of AI Inference](https://web.archive.org/web/20251001194210/https://cloud.google.com/blog/products/infrastructure/measuring-the-environmental-impact-of-ai-inference)  
- **Notes:** Google researchers (not peer reviewed). Provides per‑prompt “active processors” and “total” estimates.

### `source_oviedo`
- **Original (preprint):** [Energy Use of AI Inference: Efficiency Pathways and Test-Time Compute](https://arxiv.org/pdf/2509.20241)  
- **Notes:** Microsoft researchers (not peer reviewed). We use linear interpolation vs. token count (300 → 5,000).

### Emission/Water intensity used for scaling
- **Derived from Google disclosure:** `0.24 Wh → 0.03 g CO₂e, 0.26 mL water`  
  - Emissions intensity: **0.125 g CO₂e per Wh**  
  - Water intensity: **1.083 mL per Wh**
- Additional reference context [UK GHG methodology paper](https://web.archive.org/web/20251109020239/https://assets.publishing.service.gov.uk/media/62aee1fbe90e0765d523ca33/2022-ghg-cf-methodology-paper.pdf?utm_source=chatgpt.com)

---

## Python Reference Implementation

The function below estimates energy (Wh), CO₂ (g), and water (mL) for a given token count by combining the Google per‑prompt band (active vs. total) with a token‑scaled interpolation following *Oviedo et al.*. If `tokens` is `None` or not positive, it defaults to **5,000**.

Please see this function for the most recent version:
[https://github.com/Gene-Weaver/VoucherVisionGO/blob/main/impact.py](https://github.com/Gene-Weaver/VoucherVisionGO/blob/main/impact.py)

```python
import json

# Derived from Google disclosure: 0.24 Wh → 0.03 g CO₂e, 0.26 mL water
EMISSIONS_INTENSITY_G_PER_WH = 0.03 / 0.24      # 0.125 g CO₂e per Wh
WATER_INTENSITY_ML_PER_WH    = 0.26 / 0.24      # 1.083 mL water per Wh

def estimate_impact(tokens: float | None) -> dict:
    """
    Estimate AI inference environmental impact (energy, CO₂, water)
    combining:
      - Google (Aug 2025): active vs. total (fixed per prompt)
      - Oviedo et al. 2025: token-scaled linear interpolation
    Defaults to 5000 tokens if None, 0, or negative.
    """
    # Default token fallback
    if tokens is None or tokens <= 0:
        tokens = 5000

    # --- GOOGLE (fixed per median Gemini prompt) ---
    google_active = {"watt_hours": 0.10, 
                     "grams_CO2": 0.02, 
                     "mL_water": 0.12}
    google_total  = {"watt_hours": 0.24, 
                     "grams_CO2": 0.03, 
                     "mL_water": 0.26}

    source_google = {
        "estimate_low":  google_active,
        "estimate_high": google_total,
        "notes": ("Low - Active compute only (TPU/GPU). High - Full system CPU, RAM, idle, and PUE of 1.09. From Google Cloud Blog Aug 2025."),
        "url_source": ("https://web.archive.org/web/20251001194210/https://cloud.google.com/blog/products/infrastructure/measuring-the-environmental-impact-of-ai-inference"),
    }

    # --- OVIEDO et al. (2025): token-scaled estimates ---
    t_low, t_high = 300.0, 5000.0
    low_wh_300,  high_wh_300  = 0.18, 0.67
    low_wh_5000, high_wh_5000 = 2.38, 7.38

    def lerp(x1, y1, x2, y2, x):
        return y1 + (y2 - y1) * (x - x1) / (x2 - x1)

    low_wh  = lerp(t_low, low_wh_300,  t_high, low_wh_5000,  tokens)
    high_wh = lerp(t_low, high_wh_300, t_high, high_wh_5000, tokens)

    source_oviedo = {
        "estimate_low": {
            "watt_hours": low_wh,
            "grams_CO2": low_wh * EMISSIONS_INTENSITY_G_PER_WH,
            "mL_water": low_wh * WATER_INTENSITY_ML_PER_WH,
        },
        "estimate_high": {
            "watt_hours": high_wh,
            "grams_CO2": high_wh * EMISSIONS_INTENSITY_G_PER_WH,
            "mL_water": high_wh * WATER_INTENSITY_ML_PER_WH,
        },
        "notes": ("Linear interpolation between 300 and 5000 tokens per Oviedo et al. (2025). Water scaled using Google est. 1.083 mL per Wh ratio."),
        "url_source": ("https://arxiv.org/pdf/2509.20241"),
    }

    # --- Overall means from the 4 estimates (Google low/high + Oviedo low/high) ---
    all_wh = [
        source_google["estimate_low"]["watt_hours"],
        source_google["estimate_high"]["watt_hours"],
        source_oviedo["estimate_low"]["watt_hours"],
        source_oviedo["estimate_high"]["watt_hours"],
    ]
    all_co2 = [
        source_google["estimate_low"]["grams_CO2"],
        source_google["estimate_high"]["grams_CO2"],
        source_oviedo["estimate_low"]["grams_CO2"],
        source_oviedo["estimate_high"]["grams_CO2"],
    ]
    all_water = [
        source_google["estimate_low"]["mL_water"],
        source_google["estimate_high"]["mL_water"],
        source_oviedo["estimate_low"]["mL_water"],
        source_oviedo["estimate_high"]["mL_water"],
    ]

    est_wH = sum(all_wh) / len(all_wh)
    est_CO2 = sum(all_co2) / len(all_co2)
    est_w = sum(all_water) / len(all_water)

    return {
        "total_tokens": tokens,
        "estimate_grams_CO2": est_CO2,   # grams CO2e (mean)
        "estimate_watt_hours": est_wH,   # watt-hours (mean)
        "estimate_mL_water": est_w,      # milliliters water (mean)
        "source_google": source_google,
        "source_oviedo": source_oviedo,
    }

if __name__ == "__main__":
    for n in [5000]:
        print(json.dumps(estimate_impact(n), indent=2))
```

---
If you have corrections or better references—especially data center‑specific factors—please open an issue or contact us.
