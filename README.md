# OceanTrace V6 — SAR Oil Spill Segmentation

OceanTrace V6 is a dual-polarization SAR segmentation model designed to detect and delineate marine oil spills from Sentinel-1 SAR imagery while reducing false detections caused by clean sea and oil-spill lookalikes.

The model is part of the OceanTrace maritime intelligence pipeline, where detected oil slicks can subsequently be characterized, tracked, correlated with AIS vessel traffic, and used for forensic incident reporting.

---

## Model Overview

**Architecture:** SARDeepLabV3Plus_MultiTask_scSE  
**Framework:** PyTorch  
**Input:** 3-channel Sentinel-1 SAR representation

### Input Channels

1. `VV_norm`
2. `VH_norm`
3. `(VV - VH)_norm`

The third channel provides polarization-difference information to complement the original VV and VH backscatter channels.

### Multi-Task Design

V6 extends the segmentation network with an auxiliary scene-level classifier:

- Clean Sea
- Oil
- Lookalike

The shared encoder is equipped with a soft **scSE context gate** to improve contextual discrimination without applying a hard classifier gate to the segmentation output.

The model therefore learns both:

- pixel-level oil-spill segmentation
- scene-level discrimination between oil, clean sea, and lookalike conditions

---

## Training Configuration

| Parameter | Value |
|---|---|
| Input channels | 3 |
| Patch size | 512 × 512 |
| Encoder | DeepLabV3+ style |
| Context module | scSE |
| Scene classes | 3 |
| Segmentation loss | Focal Tversky |
| Tversky α | 0.60 |
| Tversky β | 0.40 |
| Tversky γ | 1.33 |
| Optimizer | AdamW |
| Encoder learning rate | 2e-5 |
| Head learning rate | 2e-4 |
| Batch size | 8 |
| Epochs | 30 |
| Encoder warm-up | 3 epochs |
| LR schedule | Cosine |
| Minimum LR | 1e-6 |
| Early stopping patience | 8 epochs |

Additional anti-false-positive objectives were used for:

- Lookalike suppression
- Clean-sea suppression
- Historical false-positive mining
- Morphology-diverse hard-negative mining

Training used only Parts I and II of the benchmark dataset.

**Part III was completely excluded from training and model selection.**

---

## Dataset

OceanTrace V6 was trained using the official training/validation portions of the benchmark dataset.

### Training / Validation

- **1,200 Oil** scenes
- **685 No-Oil** scenes
- **685 Lookalike** scenes

Total:

**2,570 scenes**

The dataset contains Sentinel-1 SAR imagery represented using VV and VH polarization channels.

### Official Held-Out Test

Part III contains:

- 150 Oil
- 150 No-Oil
- 150 Lookalike

Total:

**450 scenes**

Part III was kept completely untouched during training and model selection.

---

# Validation Results

The V6 training run completed 30 epochs.

### Best-IoU checkpoint — Epoch 21

Validation results:

- **Oil IoU:** 71.76%
- **Oil Recall:** 80.63%
- **Oil Precision:** 86.70%

This checkpoint was saved as:

```text
oceantrace_v6_dualpol_deeplabv3plus_best_iou.pth
```

### Best Operational checkpoint — Epoch 25

Validation operational score:

**0.5733**

Validation results:

* **Oil IoU:** 67.11%
* **Oil Recall:** 71.12%
* **Oil Precision:** 92.25%
* **No-Oil pixel FPR:** 0.0509%
* **Lookalike pixel FPR:** 0.807%

This checkpoint was saved as:

```text
oceantrace_v6_dualpol_deeplabv3plus_best_operational.pth
```

---

# Official Part III Held-Out Evaluation

The following results were obtained on the untouched official Part III test set.

No fine-tuning or calibration was performed using Part III.

Inference used deterministic center-cropping, the same V6 preprocessing pipeline, sigmoid probabilities, and **no test-time augmentation (TTA)**.

---

## Epoch 21 — Best-IoU Checkpoint

### Threshold = 0.28

This operating point provides the strongest oil-detection performance among the tested thresholds.

| Metric              |     Result |
| ------------------- | ---------: |
| Oil Global IoU      | **76.91%** |
| Oil Macro IoU       | **78.68%** |
| Oil Dice            | **86.95%** |
| Oil Recall          | **83.48%** |
| Oil Precision       | **90.72%** |
| No-Oil FP scenes    |   14 / 150 |
| Lookalike FP scenes |   94 / 150 |
| Lookalike pixel FPR |     10.28% |
| Overall IoU         |     43.18% |
| Overall Dice        |     60.31% |
| Overall Precision   |     47.21% |

### Epoch 21 threshold sweep

| Threshold |    Oil IoU |     Recall | Precision | No-Oil FP scenes | Lookalike FP scenes | Overall IoU |
| --------: | ---------: | ---------: | --------: | ---------------: | ------------------: | ----------: |
|      0.28 | **76.91%** | **83.48%** |    90.72% |               14 |                  94 |      43.18% |
|      0.30 |     69.94% |     75.72% |    90.16% |               14 |                  87 |      52.47% |
|      0.32 |     65.76% |     71.02% |    89.88% |               14 |                  79 |  **56.42%** |
|      0.34 |     63.72% |     68.64% |    89.87% |               14 |                  66 |      56.24% |
|      0.36 |     62.82% |     67.52% |    90.03% |               13 |              **55** |      56.04% |

---

## Epoch 25 — Best Operational Checkpoint

### Threshold = 0.28

| Metric              |       Result |
| ------------------- | -----------: |
| Oil Global IoU      |       57.64% |
| Oil Macro IoU       |       77.41% |
| Oil Dice            |       73.13% |
| Oil Recall          |       60.81% |
| Oil Precision       |   **91.70%** |
| No-Oil FP scenes    |  **5 / 150** |
| Lookalike FP scenes | **47 / 150** |
| Lookalike pixel FPR |   **0.854%** |
| Overall IoU         |   **54.01%** |
| Overall Dice        |   **70.14%** |
| Overall Precision   |   **82.85%** |

### Epoch 25 threshold sweep

| Threshold |    Oil IoU |     Recall |  Precision | No-Oil FP scenes | Lookalike FP scenes | Overall IoU |
| --------: | ---------: | ---------: | ---------: | ---------------: | ------------------: | ----------: |
|      0.28 | **57.64%** | **60.81%** |     91.70% |                5 |                  47 |  **54.01%** |
|      0.30 |     54.62% |     57.44% |     91.74% |                5 |                  46 |      51.74% |
|      0.32 |     51.27% |     53.70% |     91.88% |                5 |                  44 |      49.02% |
|      0.34 |     47.97% |     50.00% |     92.20% |                5 |                  41 |      46.23% |
|      0.36 |     45.58% |     47.21% | **92.98%** |                5 |              **41** |      44.19% |

---

# V3 vs V5 vs V6

Official Part III comparison:

| Model         |    Oil IoU | Oil Recall | Oil Precision | No-Oil FP | Lookalike FP |
| ------------- | ---------: | ---------: | ------------: | --------: | -----------: |
| V3            |     30.39% |     30.79% |        95.89% |     2/150 |       21/150 |
| V5            | **81.74%** | **94.74%** |        85.63% |    70/150 |      127/150 |
| V6 E21 @ 0.28 |     76.91% |     83.48% |        90.72% |    14/150 |       94/150 |
| V6 E25 @ 0.28 |     57.64% |     60.81% |    **91.70%** | **5/150** |   **47/150** |

V6 substantially improves the negative-scene behavior observed in V5 while retaining strong oil segmentation capability.

---

# Current Status

OceanTrace V6 demonstrates a significantly better balance between oil segmentation and false-positive suppression than the previous V5 model.

The two main V6 checkpoints represent different operating points:

### E21 — Detection-oriented

Higher oil recall and segmentation quality, but more lookalike false positives.

### E25 — Operational/safety-oriented

Much stronger suppression of No-Oil and Lookalike false positives, at the cost of lower oil recall.

The final deployment checkpoint, threshold, and optional test-time augmentation configuration are subject to further controlled evaluation.

---

## Reproducibility & Deployment Weights

### Primary Deployed Checkpoint (V6 E21 Final)

```text
Location: V6_E21_FINAL/oceantrace_v6_E21_final.pth
Original: oceantrace_v6_dualpol_deeplabv3plus_best_iou.pth
Epoch:    21
SHA256:   4de684fa85daf05fa9d5b330103b4e3536450ccaa9d65724f889225c13eef635
Size:     9.12 MB (9,567,755 bytes)
```

### Reference Operational Checkpoint (V6 E25)

```text
Original: oceantrace_v6_dualpol_deeplabv3plus_best_operational.pth
Epoch:    25
SHA256:   ff840f0e44a40d2f4656f56f5f9234069964cd71f75725c0e3cb9b544bce5cac
```

---

## Important Evaluation Notes

* Part III was never used for training.
* Part III was never used for fine-tuning.
* Part III was not used for model selection.
* The reported Part III results are held-out benchmark results.
* The threshold sweep was performed after model training using frozen checkpoints.
* The reported Part III evaluations used **TTA = OFF**.
* No test-time adaptation was performed.

---

## OceanTrace Pipeline

The V6 segmentation model is one component of the larger OceanTrace system:

```text
Sentinel-1 SAR
      ↓
SAR Preprocessing
      ↓
V6 Oil Spill Segmentation
      ↓
Slick Localization / Polygonization
      ↓
Spill Characterization
      ↓
Drift Hindcasting
      ↓
AIS Vessel Correlation
      ↓
Vessel Filtering & Anomaly Detection
      ↓
Responsibility Scoring
      ↓
Forensic Incident Report
```

---

## Future Work

Planned next steps include:

* controlled test-time augmentation evaluation
* final checkpoint/threshold selection
* slick polygon extraction
* spill geometry and area estimation
* drift estimation
* AIS correlation
* vessel ranking
* responsibility scoring
* integration with the OceanTrace frontend
* end-to-end forensic reporting

---

## Project

**OceanTrace — Maritime Oil Spill Intelligence**

Problem Statement:

**SIH26143 — Leveraging satellite imagery to determine oil spills at sea along with AIS data correlations to identify the vessel responsible for the spill.**
