# plaquette-curvature-profiles

Code and data for reproducing the results in:
> **Context-dependent phase structure in Z-diagonal unitaries detected via plaquette**  
> Jisung Jung

## Overview

This repository provides the simulation and QPU experiment pipelines for κ-profile diagnostics, a low-overhead method for detecting context-dependent phase structure in Z-diagonal unitaries.

## Installation

```bash
git clone https://github.com/YOUR_USERNAME/plaquette-curvature-profiles.git
cd plaquette-curvature-profiles
pip install -r requirements.txt
```

### Dependencies

- Python ≥ 3.10
- NumPy, Pandas, Matplotlib
- Qiskit, qiskit-ibm-runtime (for QPU experiments)

## Repository Structure

```
.
├── README.md
│
├── src/
│   ├── sim/                              # Simulation pipeline
│   │   ├── sim_runner.py                 # Main simulation runner
│   │   ├── sim_runner.yaml               # Configuration
│   │   ├── model_provider.py             # YAML → diagonal values
│   │   ├── stats.py                      # Statistical aggregation
│   │   ├── diagonal_model_family_grid_BFS_Shell.py  # Model generator
│   │   ├── models_grid_BFS_Shell_eta00/  # Hamiltonian models (η₃=0.0)
│   │   ├── models_grid_BFS_Shell_eta01/  # Hamiltonian models (η₃=0.1)
│   │   └── models_grid_BFS_Shell_eta02/  # Hamiltonian models (η₃=0.2)
│   │
│   └── qpu/                              # QPU experiment pipeline
│       ├── qiskit_runner.py              # IBM QPU runner (single pair)
│       ├── qiskit_runner_two_pairs.py    # Multi-pair runner
│       ├── qiskit_runner_two_pairs_block.py  # Blocked schedule
│       ├── qiskit_runner.yaml            # Configuration (single)
│       ├── qiskit_runner_two_pairs.yaml  # Configuration (multi-pair)
│       ├── model_provider.py
│       ├── diagonal_model_family_ibm_subgraph.py  # Model generator
│       ├── ibm_fez_full_20251231_220523.json      # Backend snapshot
│       ├── models_ibm_fez_eta00/         # IBM Fez models (η₃=0.0)
│       ├── models_ibm_fez_eta01/         # IBM Fez models (η₃=0.1)
│       └── models_ibm_fez_eta02/         # IBM Fez models (η₃=0.2)
│
├── figures/                              # Figure generation scripts
│   ├── fig3/                             # Sim: V_circ vs n
│   │   ├── make_fig3.py
│   │   ├── fig3_data.py
│   │   └── fig3_plot.py
│   ├── fig4/                             # Sim: κ-profile grid (n=7)
│   ├── fig5/                             # QPU: V_circ vs n
│   ├── fig6/                             # QPU: κ-profile grid
│   ├── fig7/                             # Appendix: schedule ablation
│   └── fig8/                             # Appendix: day-to-day repeatability
│
└── data/
    ├── sim/                              # Simulation results
    │   ├── grid_BFS_Shell_rows.csv
    │   ├── grid_BFS_Shell_trial_summary.csv
    │   ├── grid_BFS_Shell_run_meta.json
    │   └── grid_BFS_Shell_stats_meta.json
    │
    └── qpu/                              # QPU results (IBM Fez)
        ├── qpu_counts.json
        ├── qpu_run_meta.json
        ├── ablation_block_counts.json
        ├── ablation_block_run_meta.json
        ├── ablation_interleaved_counts.json
        └── ablation_interleaved_run_meta.json
```

## Reproducing Figures

### Main Figures (Simulation)

```bash
# Fig.3: V_circ vs n (η₃ sweep)
python figures/fig3/make_fig3.py \
  --trial-summary data/sim/grid_BFS_Shell_trial_summary.csv \
  --rows data/sim/grid_BFS_Shell_rows.csv \
  --run-meta data/sim/grid_BFS_Shell_run_meta.json \
  --stats-meta data/sim/grid_BFS_Shell_stats_meta.json \
  --out-dir outputs/fig3

# Fig.4: κ-profile grid (n=7)
python figures/fig4/make_fig4.py \
  --trial-summary-csv data/sim/grid_BFS_Shell_trial_summary.csv \
  --rows-csv data/sim/grid_BFS_Shell_rows.csv \
  --run-meta-json data/sim/grid_BFS_Shell_run_meta.json \
  --stats-meta-json data/sim/grid_BFS_Shell_stats_meta.json \
  --out-dir outputs/fig4 \
  --png
```    

### Main Figures (QPU)

```bash
# Fig.5: V_circ vs n (η₃ sweep, Day 1)
python figures/fig5/make_fig5.py \
  --counts data/qpu/qpu_counts.json \
  --run-meta data/qpu/qpu_run_meta.json \
  --out-dir outputs/fig5 \
  --eta-run 0:6 --eta-run 0.1:8 --eta-run 0.2:5

# Fig.6: κ-profile grid (QPU corroboration)
python figures/fig6/make_fig6.py \
  --counts data/qpu/qpu_counts.json \
  --run-meta data/qpu/qpu_run_meta.json \
  --out-dir outputs/fig6 \
  --eta-run 0:6 --eta-run 0.1:8 --eta-run 0.2:5
```

### Appendix Figures

```bash
# Fig.7: Schedule ablation (blocked vs interleaved)
python figures/fig7/make_fig7.py \
  --interleave-counts data/qpu/ablation_interleaved_counts.json \
  --interleave-meta data/qpu/ablation_interleaved_run_meta.json \
  --block-counts data/qpu/ablation_block_counts.json \
  --block-meta data/qpu/ablation_block_run_meta.json \
  --out-dir outputs/fig7

# Fig.8: Day-to-day repeatability
python figures/fig8/make_fig8.py \
  --counts data/qpu/qpu_counts.json \
  --out-dir outputs/fig8 \
  --day1-eta-run 0.2:5 --day1-eta-run 0.1:8 --day1-eta-run 0.0:6 \
  --day2-eta-run 0.2:7 --day2-eta-run 0.1:9 --day2-eta-run 0.0:8 \
  --n 7
```

## Data Description

### Simulation Data

| File | Description |
|------|-------------|
| `grid_BFS_Shell_rows.csv` | Per-context κ estimates |
| `grid_BFS_Shell_trial_summary.csv` | Aggregated metrics (V_circ, R, amp_min) |

### QPU Data

| File | Description |
|------|-------------|
| `qpu_counts.json` | Raw measurement counts (η₃ sweep, seeds 3 & 16) |
| `qpu_run_meta.json` | Experiment metadata |
| `ablation_*.json` | Schedule ablation experiment data |

### Parameters

- **η₃ sweep**: {0.0, 0.1, 0.2} — controls 3-local interaction strength
- **n**: 2–7 qubits
- **shots**: 2048 per circuit
- **QPU**: IBM Fez (Heron processor)

## License

MIT License. See [LICENSE](LICENSE).

## Contact

For questions or issues, please open a GitHub issue.
