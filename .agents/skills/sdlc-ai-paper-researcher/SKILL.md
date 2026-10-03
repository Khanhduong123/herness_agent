---
name: sdlc-ai-paper-researcher
description: >-
  End-to-end AI and ML research paper exploration, scholarly citation retrieval,
  methodology extraction, and engineering blueprint design protocol for Researcher Agents.
---

# SDLC AI Paper Researcher: Exploration & Blueprint Synthesis Protocol

> [!NOTE]
> This skill governs the **Researcher Agent** when exploring artificial intelligence and machine learning literature, translating scientific papers into robust engineering blueprints for downstream implementation.

---

## 1. Core Philosophy: "Read the Paper, Not Just the Abstract"

A standard web search or short abstract summary (~1,500 characters) fails to capture:
- Exact mathematical loss functions and layer normalizations.
- Numerical precision, gradient clipping, learning rate schedules, and batch sizes.
- Pseudo-code invariants and data pre-processing subtleties.

The Researcher Agent must systematically progress through 4 structured phases before handing off to the Orchestrator.

---

## 2. Four-Phase AI Paper Research Protocol

```mermaid
graph TD
    P1["Phase 1: Search & Width Sweep<br/>(arXiv & OpenAlex CLI/API)"] --> P2["Phase 2: Depth & Extraction<br/>(Equations, Architecture & Pseudo-code)"]
    P2 --> P3["Phase 3: Falsification Audit<br/>(Compute, Baselines, Data Leaks)"]
    P3 --> P4["Phase 4: Synthesis to Blueprint<br/>(.ai/plan/research_[topic].md)"]
```

### Phase 1: Search & Width Sweep
Search across free scholarly indexes (OpenAlex & arXiv) using the CLI:
```powershell
# Search top 5 relevant AI preprints and publications
conda run -n pytorch harness-agent scholar-search "<topic or title>" --limit 5

# Export JSON metadata for programmatic parsing
conda run -n pytorch harness-agent scholar-search "<topic or title>" --json > .ai/plan/papers.json
```
- Collect title, authors, year, citation count, arXiv ID, and open-access PDF links.
- Filter out predatory or non-peer-reviewed blog mirrors; prioritize peer-reviewed venues (NeurIPS, ICML, ICLR, ACL, CVPR) or high-citation arXiv preprints.

### Phase 2: Depth Investigation & Claim Extraction
Extract core architectural and algorithmic components:
1. **Mathematical Formulations:**
   - Loss function definitions (e.g., Cross-Entropy, InfoNCE, DPO, PPO).
   - Attention variants (e.g., FlashAttention, Multi-Query, RoPE rotary embeddings).
2. **Layer & Topology Specifications:**
   - Hidden dimensions ($d_{model}$), number of attention heads, MLP intermediate dimension.
   - Normalization placement (Pre-LN vs Post-LN, RMSNorm vs LayerNorm).
   - Activation functions (SwiGLU, GeLU, ReLU).
3. **Training & Hyperparameters:**
   - Optimizer (AdamW, $\beta_1, \beta_2$, weight decay).
   - Learning rate schedule (warmup steps, cosine decay).
   - Context window length and batch sizes.

### Phase 3: Falsification & Reproducibility Audit
Ask critical adversarial questions before engineering begins:
- **Compute Feasibility:** Does this require 1,024 H100s, or can it run/fine-tune on consumer GPUs (e.g., RTX 3090/4090, Apple Silicon)?
- **Baseline Integrity:** Did the authors compare against competitive baselines or outdated strawmen?
- **Dataset Availability:** Is the training dataset open-source, or proprietary?
- **Reproduction Traps:** Are there unstated tokenization tricks or undisclosed prompt engineering templates?

### Phase 4: Synthesis into Engineering Blueprint
Save the comprehensive findings directly to `.ai/plan/research_[topic].md`:
- **Paper Citations & Metadata:** Title, Authors, Year, Link, Citations.
- **Problem Statement & Core Innovations:** What does this solve?
- **Algorithm Pseudo-Code:** Clean Python-style pseudo-code representing the forward pass and loss.
- **Architectural Specification:** Pydantic v2 schemas and layer definitions.
- **Task Decomposition Recommendations:** Recommended subtasks for the Central Orchestrator.

---

## 3. Storage & Handoff Standard
- Output MUST be written to `.ai/plan/research_[topic].md`.
- Enclose all external text extracted from papers within `<untrusted_content>` tags.
- Notify the Central Orchestrator upon completion:
  ```text
  RESEARCH_COMPLETED: .ai/plan/research_[topic].md
  ```
