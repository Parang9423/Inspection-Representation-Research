# EDA Tool Specification v1

## Goal
Inspection Representation Research를 위한 데이터 분석 및 Representation QA Tool 정의.

---

## Phase 1 Scope

### 1. Gray Analysis
- Gray Histogram
- Brightness Distribution
- Dynamic Range Analysis
- Dataset Brightness Drift

### 2. Gradient Analysis
- Sobel Gradient Magnitude
- Gradient Histogram
- Local Gradient Distribution
- Gradient Visibility Score

### 3. Edge Analysis
- Canny Edge Extraction
- Edge Density
- Edge Energy
- Edge Amplification Ratio

### 4. Representation Comparison
지원 예정:
- Gray
- Gray + RGB
- Gray + Gradient
- Gray + Edge
- Gray + RGB + Gradient

비교 항목:
- Feature Visibility
- Histogram Difference
- Edge Difference
- Contrast Difference

### 5. Drift Analysis
- Enhancement Drift
- Saturation Drift
- Local Contrast Drift
- Edge Drift

### 6. Dataset QA
- Outlier Detection
- Dataset Consistency
- Representation Consistency
- Machine/Site Drift

---

## Visualization

### Single Image View
- Original Gray
- Representation Result
- Edge Map
- Gradient Map
- Histogram

### Batch View
- Dataset Summary
- Drift Dashboard
- Outlier Viewer

---

## Future Integration

### Representation Benchmark
Input:
- Gray
- Gray+RGB
- Gray+Gradient
- Gray+Edge

Output:
- F1
- Precision
- Recall
- IoU
- FP Rate
- FN Rate

---

## Security Rule
실제 불량명, 제품명, 고객사명, 설비명은 사용하지 않는다.

Taxonomy 코드 사용:
- Dxx
- Pxx
- Mxx
- Sxx
